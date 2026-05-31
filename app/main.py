import logging
import os
import time

import yaml

from flat import FlatCollector
from modbus import ModbusConnection
from sinks import InfluxSink, MqttSink
from sunspec import SunSpecCollector


def _load_config(path: str) -> dict:
    if not os.path.exists(path):
        logging.getLogger("kostal_bridge").warning("Config file not found: %s", path)
        return {"models": {}}
    with open(path, "r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        return {"models": {}}
    loaded.setdefault("models", {})
    return loaded


def _touch_heartbeat() -> None:
    with open("/tmp/bridge_heartbeat", "w", encoding="utf-8") as f:
        f.write(str(time.time()))


def main() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level_name, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("kostal_bridge")

    config_path = os.getenv("BRIDGE_CONFIG", "/config/registers.yml")
    poll_interval = float(os.getenv("POLL_INTERVAL", "5"))

    primary = os.getenv("MODBUS_HOST", "kostal-wr.home")
    fallback = os.getenv("MODBUS_HOST_FALLBACK", "192.168.178.53")
    hosts = [primary]
    if fallback and fallback != primary:
        hosts.append(fallback)

    modbus = ModbusConnection(
        hosts=hosts,
        port=int(os.getenv("MODBUS_PORT", "1502")),
        unit_id=int(os.getenv("MODBUS_UNIT_ID", "71")),
        timeout=float(os.getenv("MODBUS_TIMEOUT", "5")),
    )

    config = _load_config(config_path)
    sunspec = SunSpecCollector(modbus, config.get("models", {}))
    flat = FlatCollector(modbus, config.get("flat_registers", []))
    influx = InfluxSink()
    mqtt = MqttSink()

    while True:
        start = time.time()
        try:
            if modbus.ensure():
                sunspec.invalidate()
            points = sunspec.collect() + flat.collect()
            influx.write(points, source=modbus.active_host or "unknown")
            mqtt.publish(points)
            _touch_heartbeat()
            logger.info("Cycle done: %d points via %s", len(points), modbus.active_host)
        except Exception as exc:
            logger.exception("Cycle failed: %s", exc)
            modbus.reset()
            sunspec.invalidate()
            time.sleep(min(poll_interval, 5))

        elapsed = time.time() - start
        time.sleep(max(0.5, poll_interval - elapsed))


if __name__ == "__main__":
    main()
