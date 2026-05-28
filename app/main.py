import json
import logging
import math
import os
import socket
import struct
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import yaml
from influxdb import InfluxDBClient
from paho.mqtt import client as mqtt
from pymodbus.client import ModbusTcpClient


@dataclass
class DecodedPoint:
    model: int
    point: str
    value: Any
    unit: str = ""


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def sanitize_topic_part(value: str) -> str:
    out = []
    for ch in value.lower():
        if ch.isalnum() or ch in {"_", "-"}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_") or "unknown"


def cdab_u32(reg_hi: int, reg_lo: int) -> int:
    a = (reg_hi >> 8) & 0xFF
    b = reg_hi & 0xFF
    c = (reg_lo >> 8) & 0xFF
    d = reg_lo & 0xFF
    return (c << 24) | (d << 16) | (a << 8) | b


def decode_typed(regs: List[int], offset: int, dtype: str) -> Any:
    if offset < 0 or offset >= len(regs):
        raise IndexError(f"Offset {offset} out of range")

    if dtype == "u16":
        return int(regs[offset])
    if dtype == "i16":
        value = regs[offset]
        return value - 65536 if value > 32767 else value
    if dtype in {"u32_cdab", "i32_cdab", "f32_cdab"}:
        if offset + 1 >= len(regs):
            raise IndexError(f"Offset {offset} requires 2 registers")
        raw = cdab_u32(regs[offset], regs[offset + 1])
        if dtype == "u32_cdab":
            return raw
        if dtype == "i32_cdab":
            return struct.unpack(">i", raw.to_bytes(4, byteorder="big", signed=False))[0]
        return struct.unpack(">f", raw.to_bytes(4, byteorder="big", signed=False))[0]

    raise ValueError(f"Unsupported dtype: {dtype}")


def decode_i16(regs: List[int], offset: int) -> int:
    if offset < 0 or offset >= len(regs):
        raise IndexError(f"Offset {offset} out of range")
    value = int(regs[offset])
    return value - 65536 if value > 32767 else value


class KostalBridge:
    def __init__(self) -> None:
        self.modbus_primary = os.getenv("MODBUS_HOST", "kostal-wr.home")
        self.modbus_fallback = os.getenv("MODBUS_HOST_FALLBACK", "192.168.178.53")
        self.modbus_port = int(os.getenv("MODBUS_PORT", "1502"))
        self.modbus_unit_id = int(os.getenv("MODBUS_UNIT_ID", "71"))
        self.modbus_timeout = float(os.getenv("MODBUS_TIMEOUT", "5"))
        self.poll_interval = float(os.getenv("POLL_INTERVAL", "5"))

        self.influx_host = os.getenv("INFLUX_HOST", "influxdb")
        self.influx_port = int(os.getenv("INFLUX_PORT", "8086"))
        self.influx_db = os.getenv("INFLUX_DB", "kostal")
        self.influx_user = os.getenv("INFLUX_USER", "")
        self.influx_pass = os.getenv("INFLUX_PASS", "")
        self.influx_ssl = env_bool("INFLUX_SSL", False)
        self.influx_verify_ssl = env_bool("INFLUX_VERIFY_SSL", True)
        self.influx_measurement = os.getenv("INFLUX_MEASUREMENT", "kostal_plenticore")

        self.mqtt_host = os.getenv("MQTT_HOST", "mosquitto")
        self.mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
        self.mqtt_user = os.getenv("MQTT_USER", "")
        self.mqtt_pass = os.getenv("MQTT_PASS", "")
        self.mqtt_topic_prefix = os.getenv("MQTT_TOPIC_PREFIX", "home/kostal/plenticore").rstrip("/")
        self.mqtt_client_id = os.getenv("MQTT_CLIENT_ID", "kostal-bridge")
        self.mqtt_tls = env_bool("MQTT_TLS", False)
        self.mqtt_keepalive = int(os.getenv("MQTT_KEEPALIVE", "60"))
        self.mqtt_qos = int(os.getenv("MQTT_QOS", "0"))
        self.mqtt_retain = env_bool("MQTT_RETAIN", False)

        self.log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        self.bridge_config = os.getenv("BRIDGE_CONFIG", "/config/registers.yml")

        self.modbus_hosts = [self.modbus_primary]
        if self.modbus_fallback and self.modbus_fallback != self.modbus_primary:
            self.modbus_hosts.append(self.modbus_fallback)

        self.logger = logging.getLogger("kostal_bridge")
        self.modbus_client: Optional[ModbusTcpClient] = None
        self.active_modbus_host: Optional[str] = None
        self.sunspec_base: Optional[int] = None
        self.models: List[Tuple[int, int, int]] = []

        self.config = self._load_config()
        self.influx_client = self._init_influx()
        self.mqtt_client = self._init_mqtt()

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.bridge_config):
            self.logger.warning("Config file not found: %s", self.bridge_config)
            return {"models": {}}

        with open(self.bridge_config, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}

        if not isinstance(loaded, dict):
            return {"models": {}}
        loaded.setdefault("models", {})
        return loaded

    def _init_influx(self) -> InfluxDBClient:
        client = InfluxDBClient(
            host=self.influx_host,
            port=self.influx_port,
            username=self.influx_user or None,
            password=self.influx_pass or None,
            ssl=self.influx_ssl,
            verify_ssl=self.influx_verify_ssl,
            database=self.influx_db,
            timeout=10,
        )
        client.create_database(self.influx_db)
        client.switch_database(self.influx_db)
        self.logger.info("InfluxDB ready at %s:%s/%s", self.influx_host, self.influx_port, self.influx_db)
        return client

    def _init_mqtt(self) -> mqtt.Client:
        client = mqtt.Client(client_id=self.mqtt_client_id, clean_session=True)
        if self.mqtt_user:
            client.username_pw_set(self.mqtt_user, self.mqtt_pass)
        if self.mqtt_tls:
            client.tls_set()

        client.connect(self.mqtt_host, self.mqtt_port, keepalive=self.mqtt_keepalive)
        client.loop_start()
        self.logger.info("MQTT ready at %s:%s", self.mqtt_host, self.mqtt_port)
        return client

    def _connect_modbus(self) -> None:
        for host in self.modbus_hosts:
            if not host:
                continue
            try:
                socket.gethostbyname(host)
            except socket.gaierror:
                self.logger.warning("Host not resolvable: %s", host)
                continue

            client = ModbusTcpClient(host=host, port=self.modbus_port, timeout=self.modbus_timeout)
            if client.connect():
                self.modbus_client = client
                self.active_modbus_host = host
                self.logger.info("Connected to Modbus host %s:%s", host, self.modbus_port)
                return

            self.logger.warning("Could not connect to Modbus host %s:%s", host, self.modbus_port)
            client.close()

        raise ConnectionError("Unable to connect to any configured Modbus host")

    def _ensure_modbus(self) -> None:
        if self.modbus_client is None:
            self._connect_modbus()
            self.sunspec_base = None
            self.models = []
            return

        if not self.modbus_client.connected:
            self.logger.warning("Modbus connection dropped. Reconnecting.")
            try:
                self.modbus_client.close()
            except Exception:
                pass
            self.modbus_client = None
            self._connect_modbus()
            self.sunspec_base = None
            self.models = []

    def _read_holding(self, address: int, count: int) -> List[int]:
        assert self.modbus_client is not None
        response = self.modbus_client.read_holding_registers(address=address, count=count, slave=self.modbus_unit_id)
        if response.isError():
            raise RuntimeError(f"Modbus read failed at {address} count={count}: {response}")
        return list(response.registers)

    def _discover_sunspec(self) -> None:
        if self.sunspec_base is not None and self.models:
            return

        self.logger.info("Running SunSpec discovery")
        candidate_bases = [40000, 39999, 50000, 0]
        found_base = None
        for base in candidate_bases:
            try:
                regs = self._read_holding(base, 2)
                if regs == [0x5375, 0x6E53]:  # 'SunS'
                    found_base = base
                    break
            except Exception:
                continue

        if found_base is None:
            raise RuntimeError("SunSpec marker not found on known base addresses")

        self.sunspec_base = found_base
        self.logger.info("SunSpec marker found at base %s", found_base)

        models: List[Tuple[int, int, int]] = []
        cursor = found_base + 2
        for _ in range(512):
            header = self._read_holding(cursor, 2)
            model_id, model_len = int(header[0]), int(header[1])

            if model_id == 0xFFFF:
                break
            if model_len <= 0 or model_len > 2048:
                raise RuntimeError(f"Invalid model length for model {model_id}: {model_len}")

            data_address = cursor + 2
            models.append((model_id, data_address, model_len))
            cursor = data_address + model_len

        if not models:
            raise RuntimeError("No SunSpec models discovered")

        self.models = models
        self.logger.info("Discovered %d SunSpec models", len(models))

    def _decode_model_generic(self, model_id: int, regs: List[int]) -> List[DecodedPoint]:
        points: List[DecodedPoint] = []
        for i, reg in enumerate(regs):
            points.append(DecodedPoint(model=model_id, point=f"r{i}_u16", value=int(reg)))

        for i in range(0, len(regs) - 1, 2):
            raw_u32 = cdab_u32(regs[i], regs[i + 1])
            points.append(DecodedPoint(model=model_id, point=f"r{i}_u32_cdab", value=int(raw_u32)))

            signed = struct.unpack(">i", raw_u32.to_bytes(4, byteorder="big", signed=False))[0]
            points.append(DecodedPoint(model=model_id, point=f"r{i}_i32_cdab", value=int(signed)))

            float_value = struct.unpack(">f", raw_u32.to_bytes(4, byteorder="big", signed=False))[0]
            if math.isfinite(float_value):
                points.append(DecodedPoint(model=model_id, point=f"r{i}_f32_cdab", value=float(float_value)))

        return points

    def _decode_model_configured(self, model_id: int, regs: List[int]) -> List[DecodedPoint]:
        model_cfg = self.config.get("models", {}).get(str(model_id), {})
        configured_points = model_cfg.get("points", [])
        decoded: List[DecodedPoint] = []

        if not isinstance(configured_points, list):
            return decoded

        for item in configured_points:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            offset = item.get("offset")
            dtype = item.get("type")
            unit = item.get("unit", "")
            scale_from = item.get("scale_from")
            enum_map = item.get("enum_map", {})
            if name is None or offset is None or dtype is None:
                continue

            try:
                value = decode_typed(regs=regs, offset=int(offset), dtype=str(dtype))

                if scale_from is not None and isinstance(value, (int, float)):
                    sf = decode_i16(regs, int(scale_from))
                    if sf != -32768:
                        value = float(value) * (10 ** sf)

                if isinstance(enum_map, dict):
                    value = enum_map.get(str(value), value)

                decoded.append(DecodedPoint(model=model_id, point=sanitize_topic_part(str(name)), value=value, unit=str(unit)))
            except Exception as exc:
                self.logger.debug("Skipping configured point model=%s name=%s due to %s", model_id, name, exc)

        return decoded

    def _collect_points(self) -> List[DecodedPoint]:
        self._ensure_modbus()
        self._discover_sunspec()
        assert self.modbus_client is not None

        all_points: List[DecodedPoint] = []
        for model_id, data_address, model_len in self.models:
            regs = self._read_holding(data_address, model_len)
            all_points.extend(self._decode_model_generic(model_id, regs))
            all_points.extend(self._decode_model_configured(model_id, regs))

        return all_points

    def _publish_mqtt(self, points: List[DecodedPoint]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for p in points:
            model_part = sanitize_topic_part(f"m{p.model}")
            point_part = sanitize_topic_part(p.point)
            topic = f"{self.mqtt_topic_prefix}/{model_part}/{point_part}"

            payload: str
            if isinstance(p.value, (int, float)):
                payload = str(p.value)
            else:
                payload = json.dumps({"value": p.value, "ts": now, "unit": p.unit}, separators=(",", ":"))

            info = self.mqtt_client.publish(topic, payload=payload, qos=self.mqtt_qos, retain=self.mqtt_retain)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish failed rc={info.rc} topic={topic}")

    def _write_influx(self, points: List[DecodedPoint]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        body: List[Dict[str, Any]] = []

        for p in points:
            tags = {
                "source": self.active_modbus_host or "unknown",
                "model": f"m{p.model}",
                "point": p.point,
            }
            if p.unit:
                tags["unit"] = p.unit

            fields: Dict[str, Any] = {}
            if isinstance(p.value, bool):
                fields["value_bool"] = p.value
            elif isinstance(p.value, int):
                fields["value_int"] = p.value
                fields["value"] = float(p.value)
            elif isinstance(p.value, float):
                if math.isfinite(p.value):
                    fields["value"] = p.value
                else:
                    continue
            else:
                fields["value_str"] = str(p.value)

            body.append(
                {
                    "measurement": self.influx_measurement,
                    "tags": tags,
                    "time": now,
                    "fields": fields,
                }
            )

        if body:
            self.influx_client.write_points(body, time_precision="s", batch_size=2000)

    def _touch_heartbeat(self) -> None:
        with open("/tmp/bridge_heartbeat", "w", encoding="utf-8") as f:
            f.write(str(time.time()))

    def run(self) -> None:
        while True:
            start = time.time()
            try:
                points = self._collect_points()
                self._write_influx(points)
                self._publish_mqtt(points)
                self._touch_heartbeat()
                self.logger.info(
                    "Cycle done: %d points from %d models via %s",
                    len(points),
                    len(self.models),
                    self.active_modbus_host,
                )
            except Exception as exc:
                self.logger.exception("Cycle failed: %s", exc)
                if self.modbus_client is not None:
                    try:
                        self.modbus_client.close()
                    except Exception:
                        pass
                    self.modbus_client = None
                time.sleep(min(self.poll_interval, 5))

            elapsed = time.time() - start
            sleep_for = max(0.5, self.poll_interval - elapsed)
            time.sleep(sleep_for)


if __name__ == "__main__":
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    bridge = KostalBridge()
    bridge.run()
