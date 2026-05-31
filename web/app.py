import os
import socket
import time
from datetime import datetime, timezone
import yaml
from flask import Flask, jsonify, send_file
from influxdb import InfluxDBClient

app = Flask(__name__)

_INFLUX_HOST = os.getenv("INFLUX_HOST", "influxdb")
_INFLUX_PORT = int(os.getenv("INFLUX_PORT", 8086))
_INFLUX_DB = os.getenv("INFLUX_DB", "kostal")
_INFLUX_USER = os.getenv("INFLUX_USER", "kostal")
_INFLUX_PASS = os.getenv("INFLUX_PASS", "kostalpass")
_MEASUREMENT = os.getenv("INFLUX_MEASUREMENT", "kostal_plenticore")
_MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
_MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
_CONFIG_PATH = os.getenv("BRIDGE_CONFIG", "/config/registers.yml")
_INDEX_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


def _client():
    return InfluxDBClient(
        host=_INFLUX_HOST, port=_INFLUX_PORT,
        username=_INFLUX_USER, password=_INFLUX_PASS,
        database=_INFLUX_DB, timeout=3,
    )


def _load_config():
    try:
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _series(rs):
    """Yield (tags, row_dict) pairs from a raw InfluxDB ResultSet.

    influxdb-python sets rs.raw to results[0] directly (not the full envelope).
    """
    for s in rs.raw.get("series", []):
        tags = s.get("tags") or {}
        cols = s.get("columns", [])
        for row in s.get("values", []):
            yield tags, dict(zip(cols, row))


@app.route("/")
def index():
    return send_file(_INDEX_HTML)


@app.route("/api/status")
def api_status():
    influx_ok, influx_ms = False, None
    try:
        t0 = time.time()
        _client().ping()
        influx_ms = round((time.time() - t0) * 1000)
        influx_ok = True
    except Exception:
        pass

    mqtt_ok = False
    try:
        with socket.create_connection((_MQTT_HOST, _MQTT_PORT), timeout=2):
            mqtt_ok = True
    except Exception:
        pass

    bridge_ok, age_s, bridge_err = False, None, None
    try:
        c = _client()
        ts_str = None
        for field in ("value", "value_str", "value_int"):
            rs = c.query(f'SELECT LAST({field}) FROM "{_MEASUREMENT}"')
            rows = list(_series(rs))
            if rows:
                ts_str = rows[0][1].get("time")
                break
        if ts_str:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            age_s = round((datetime.now(timezone.utc) - ts).total_seconds())
            bridge_ok = age_s < 120
    except Exception as e:
        bridge_err = str(e)

    return jsonify({
        "influxdb": {"ok": influx_ok, "latency_ms": influx_ms},
        "mqtt": {"ok": mqtt_ok},
        "bridge": {"ok": bridge_ok, "heartbeat_age_s": age_s, "error": bridge_err},
    })


@app.route("/api/values")
def api_values():
    cfg = _load_config()
    model_order = []
    mapped_per_model = {}
    for mid, mcfg in cfg.get("models", {}).items():
        key = f"m{mid}"
        model_order.append(key)
        mapped_per_model[key] = [p["name"] for p in (mcfg or {}).get("points", [])]

    collected: dict = {}
    try:
        c = _client()
        for q in [
            f'SELECT LAST(value) AS val FROM "{_MEASUREMENT}" GROUP BY model, point, unit',
            f'SELECT LAST(value_str) AS val FROM "{_MEASUREMENT}" GROUP BY model, point, unit',
        ]:
            for tags, row in _series(c.query(q)):
                if row.get("val") is None:
                    continue
                k = (tags.get("model", ""), tags.get("point", ""))
                if k not in collected:
                    collected[k] = {
                        "model": tags.get("model", ""),
                        "point": tags.get("point", ""),
                        "unit": tags.get("unit", ""),
                        "value": row["val"],
                    }
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    grouped: dict = {}
    for (model, point_name), data in collected.items():
        is_mapped = point_name in mapped_per_model.get(model, [])
        grouped.setdefault(model, []).append({
            "name": point_name,
            "value": data["value"],
            "unit": data["unit"],
            "mapped": is_mapped,
        })

    for model, pts in grouped.items():
        order = {n: i for i, n in enumerate(mapped_per_model.get(model, []))}
        pts.sort(key=lambda p: (0, order.get(p["name"], 9999)) if p["mapped"] else (1, p["name"]))

    result = {}
    for k in model_order:
        if k in grouped:
            result[k] = grouped[k]
    for k in sorted(grouped):
        if k not in result:
            result[k] = grouped[k]
    return jsonify(result)


@app.route("/api/config")
def api_config():
    cfg = _load_config()
    models = {
        f"m{mid}": [p["name"] for p in (mcfg or {}).get("points", [])]
        for mid, mcfg in cfg.get("models", {}).items()
    }
    return jsonify({"models": models})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
