import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from influxdb import InfluxDBClient
from paho.mqtt import client as mqtt

from decoders import DecodedPoint, env_bool, sanitize_topic_part

logger = logging.getLogger("kostal_bridge.sinks")


class InfluxSink:
    def __init__(self) -> None:
        host = os.getenv("INFLUX_HOST", "influxdb")
        port = int(os.getenv("INFLUX_PORT", "8086"))
        db = os.getenv("INFLUX_DB", "kostal")
        user = os.getenv("INFLUX_USER", "")
        password = os.getenv("INFLUX_PASS", "")
        ssl = env_bool("INFLUX_SSL", False)
        verify_ssl = env_bool("INFLUX_VERIFY_SSL", True)
        self.measurement = os.getenv("INFLUX_MEASUREMENT", "kostal_plenticore")

        self._client = InfluxDBClient(
            host=host,
            port=port,
            username=user or None,
            password=password or None,
            ssl=ssl,
            verify_ssl=verify_ssl,
            database=db,
            timeout=10,
        )
        self._client.create_database(db)
        self._client.switch_database(db)
        logger.info("InfluxDB ready at %s:%s/%s", host, port, db)

    def write(self, points: List[DecodedPoint], source: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        body: List[Dict[str, Any]] = []

        for p in points:
            tags = {
                "source": source,
                "model": p.model,
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

            body.append({
                "measurement": self.measurement,
                "tags": tags,
                "time": now,
                "fields": fields,
            })

        if body:
            self._client.write_points(body, time_precision="s", batch_size=2000)


class MqttSink:
    def __init__(self) -> None:
        host = os.getenv("MQTT_HOST", "mosquitto")
        port = int(os.getenv("MQTT_PORT", "1883"))
        user = os.getenv("MQTT_USER", "")
        password = os.getenv("MQTT_PASS", "")
        client_id = os.getenv("MQTT_CLIENT_ID", "kostal-bridge")
        tls = env_bool("MQTT_TLS", False)
        keepalive = int(os.getenv("MQTT_KEEPALIVE", "60"))
        self.topic_prefix = os.getenv("MQTT_TOPIC_PREFIX", "home/kostal/plenticore").rstrip("/")
        self.qos = int(os.getenv("MQTT_QOS", "0"))
        self.retain = env_bool("MQTT_RETAIN", False)

        self._client = mqtt.Client(client_id=client_id, clean_session=True)
        if user:
            self._client.username_pw_set(user, password)
        if tls:
            self._client.tls_set()

        self._client.connect(host, port, keepalive=keepalive)
        self._client.loop_start()
        logger.info("MQTT ready at %s:%s", host, port)

    def publish(self, points: List[DecodedPoint]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for p in points:
            model_part = sanitize_topic_part(p.model)
            point_part = sanitize_topic_part(p.point)
            topic = f"{self.topic_prefix}/{model_part}/{point_part}"

            if isinstance(p.value, (int, float)):
                payload = str(p.value)
            else:
                payload = json.dumps({"value": p.value, "ts": now, "unit": p.unit}, separators=(",", ":"))

            info = self._client.publish(topic, payload=payload, qos=self.qos, retain=self.retain)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise RuntimeError(f"MQTT publish failed rc={info.rc} topic={topic}")
