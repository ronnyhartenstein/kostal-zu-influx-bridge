"""Read-only MCP-Server auf die Influx-Daten. Schreibende Tools gibt es hier bewusst nicht."""
import os
import re
from datetime import datetime, timezone
from typing import NamedTuple

import uvicorn
import yaml
from influxdb import InfluxDBClient
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

DB = os.getenv("INFLUX_DB", "kostal")
MEASUREMENT = os.getenv("INFLUX_MEASUREMENT", "kostal_plenticore")
CONFIG_PATH = os.getenv("BRIDGE_CONFIG", "/config/registers.yml")
DATABASES = tuple(os.getenv("MCP_DATABASES", DB).split(","))
NOTES = os.getenv("MCP_NOTES", "")  # Hinweise der Installation, z. B. bekannte Datenlücken
TZ = "Europe/Berlin"
MAX_ROWS = 2000

INSTRUCTIONS = (
    "Nur lesender Zugriff auf die Messdaten eines Kostal-Wechselrichters in InfluxDB. "
    "Mit get_overview beginnen, Punktnamen liefert list_points. Leistungen haben das Suffix _w, "
    "Zähler wie gesamtertrag_wh sind fortlaufend: Energie je Zeitraum ist die Differenz, nicht die Summe. "
    "Echte PV-Leistung ist dc_leistung_pv_alternativ_w; dc_leistung_gesamt_w enthält die Batterie."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)

_DURATION = re.compile(r"^\d+[mhd]$")
_POINT = re.compile(r"^[a-z0-9_]+$")
_INTO = re.compile(r"\bINTO\b", re.IGNORECASE)
_STRINGS = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}


class Tier(NamedTuple):
    """Eine Datenstufe: Retention Policy, Auflösung in Sekunden, Feld je Aggregat."""
    policy: str
    resolution: int
    field: str


RAW = Tier("autogen", 0, "value")
# Der Stack aus diesem Repo verdichtet nach rp_1min und rp_5min, Mini nach downsample mit eigenen Feldnamen.
LAYOUTS = {
    "downsample": [RAW, Tier("downsample", 300, "{aggregate}_value_5m")],
    "rp_5min": [RAW, Tier("rp_1min", 60, "value"), Tier("rp_5min", 300, "value")],
}


def client(database: str = DB) -> InfluxDBClient:
    return InfluxDBClient(
        host=os.getenv("INFLUX_HOST", "influxdb"), port=int(os.getenv("INFLUX_PORT", 8086)),
        username=os.getenv("INFLUX_USER", ""), password=os.getenv("INFLUX_PASS", ""),
        database=database, timeout=30,
    )


def check_query(query: str) -> str:
    """Lässt nur eine einzelne SELECT- oder SHOW-Anweisung ohne INTO durch."""
    text = query.strip().rstrip(";").strip()
    bare = _STRINGS.sub("''", text)
    if ";" in bare:
        raise ToolError("Nur eine Anweisung pro Aufruf")
    if not re.match(r"(SELECT|SHOW)\b", bare, re.IGNORECASE):
        raise ToolError("Nur SELECT und SHOW sind erlaubt")
    if _INTO.search(bare):
        raise ToolError("SELECT INTO ist nicht erlaubt")
    return text


def run(query: str, database: str = DB) -> list[dict]:
    """Abfrage per GET: InfluxDB nimmt darüber keine schreibenden Anweisungen an."""
    result = client(database).query(query, method="GET")
    sets = result if isinstance(result, list) else [result]
    series = []
    for rs in sets:
        for s in rs.raw.get("series", []):
            rows = [dict(zip(s["columns"], row)) for row in s.get("values", [])]
            series.append({"name": s.get("name"), "tags": s.get("tags") or {}, "rows": rows})
    return series


def seconds(duration: str) -> int:
    if not _DURATION.match(duration):
        raise ToolError(f"Ungültige Dauer {duration!r}, erlaubt sind z. B. 5m, 1h, 1d")
    return int(duration[:-1]) * _UNIT_SECONDS[duration[-1]]


def parse_time(value: str) -> datetime:
    """Nimmt ISO-Zeiten, ohne Zeitzone gilt UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def retention_seconds(duration: str) -> float:
    """InfluxDB meldet z. B. 168h0m0s, 0s heißt unbegrenzt."""
    parts = {unit: int(n) for n, unit in re.findall(r"(\d+)([hms])", duration)}
    total = parts.get("h", 0) * 3600 + parts.get("m", 0) * 60 + parts.get("s", 0)
    return total or float("inf")


def load_retention() -> dict[str, float]:
    return {r["name"]: retention_seconds(r["duration"])
            for s in run(f'SHOW RETENTION POLICIES ON "{DB}"') for r in s["rows"]}


def choose_tier(retention: dict[str, float], start: datetime, step: int, now: datetime) -> Tier:
    """Die gröbste Stufe, die fein genug ist und bis start zurückreicht."""
    layout = next((tiers for marker, tiers in LAYOUTS.items() if marker in retention), [RAW])
    age = (now - start).total_seconds()
    covering = [t for t in layout if retention.get(t.policy, 0) > age]
    if not covering:
        raise ToolError("Für diesen Zeitraum gibt es keine Daten")
    usable = [t for t in covering if t.resolution <= step]
    if not usable:
        raise ToolError(f"So weit zurück gibt es nur Werte im Abstand von {covering[0].resolution} Sekunden, "
                        "Intervall vergrößern")
    return usable[-1]


def history_query(points: list[str], start: datetime, end: datetime, interval: str, aggregate: str,
                  now: datetime, retention: dict[str, float]) -> str:
    if aggregate not in ("mean", "min", "max"):
        raise ToolError("aggregate muss mean, min oder max sein")
    if not points or any(not _POINT.match(p) for p in points):
        raise ToolError("Ungültige Punktnamen, siehe list_points")
    step = seconds(interval)
    tier = choose_tier(retention, start, step, now)
    if (end - start).total_seconds() / step > MAX_ROWS:
        raise ToolError(f"Mehr als {MAX_ROWS} Werte je Punkt, Intervall vergrößern")
    field = tier.field.format(aggregate=aggregate)
    selected = " OR ".join(f"\"point\" = '{p}'" for p in points)
    bounds = f"time >= '{start.isoformat()}' AND time < '{end.isoformat()}'"
    return (f'SELECT {aggregate}("{field}") AS "value" FROM "{tier.policy}"."{MEASUREMENT}" '
            f'WHERE ({selected}) AND {bounds} GROUP BY time({interval}), "point" fill(none) tz(\'{TZ}\')')


def load_points() -> list[dict]:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f) or {}
    points = [{"model": f"m{mid}", "name": p["name"], "unit": p.get("unit")}
              for mid, model in (cfg.get("models") or {}).items() for p in (model or {}).get("points", [])]
    points += [{"model": "flat", "name": r["name"], "unit": r.get("unit")}
               for r in cfg.get("flat_registers") or [] if isinstance(r, dict)]
    return points


def create() -> MCPServer:
    mcp = MCPServer("kostal", instructions=f"{INSTRUCTIONS} {NOTES}".strip())
    tool = lambda: mcp.tool(annotations=READ_ONLY)

    @tool()
    def get_overview() -> dict:
        """Datenbanken mit Measurements und Aufbewahrung, Zeitpunkt des jüngsten Messwerts."""
        latest = run(f'SELECT last("value") FROM "autogen"."{MEASUREMENT}" WHERE time > now() - 1h')
        databases = {name: {"measurements": [r["name"] for s in run("SHOW MEASUREMENTS", name) for r in s["rows"]],
                            "retention": [{k: r[k] for k in ("name", "duration")}
                                          for s in run(f'SHOW RETENTION POLICIES ON "{name}"', name)
                                          for r in s["rows"]]}
                     for name in DATABASES}
        return {"databases": databases, "timezone": TZ, "latest_write": latest[0]["rows"][0]["time"] if latest else None}

    @tool()
    def list_points(query: str | None = None, model: str | None = None) -> dict:
        """Exportierte Messpunkte mit Modell und Einheit, optional nach Namensteil oder Modell (m103, flat) gefiltert."""
        items = [p for p in load_points()
                 if (not query or query.lower() in p["name"]) and (not model or p["model"] == model)]
        return {"total": len(items), "items": items}

    @tool()
    def get_latest(query: str | None = None) -> dict:
        """Jüngste Werte der letzten Stunde je Punkt, optional nach Namensteil gefiltert."""
        values = {}
        for field in ("value", "value_str", "value_bool"):
            q = f'SELECT last("{field}") AS "v" FROM "autogen"."{MEASUREMENT}" WHERE time > now() - 1h GROUP BY "point", "unit"'
            for s in run(q):
                name = s["tags"]["point"]
                if not query or query.lower() in name:
                    values.setdefault(name, {"value": s["rows"][0]["v"], "unit": s["tags"].get("unit") or None,
                                             "time": s["rows"][0]["time"]})
        return {"total": len(values), "items": [{"point": k} | v for k, v in sorted(values.items())]}

    @tool()
    def get_history(points: list[str], start: str, end: str | None = None, interval: str = "5m",
                    aggregate: str = "mean") -> dict:
        """Zeitreihen numerischer Punkte. start/end als ISO-Zeit (ohne Zeitzone: UTC), end fehlt = jetzt.

        interval z. B. 1m, 5m, 1h, 1d; Tagesgrenzen gelten in Europe/Berlin. aggregate: mean, min, max.
        Die Datenstufe folgt aus Zeitraum und Intervall; die Abfrage steht im Ergebnis."""
        now = datetime.now(timezone.utc)
        query = history_query(points, parse_time(start), parse_time(end) if end else now, interval, aggregate,
                              now, load_retention())
        return {"query": query, "series": [{"point": s["tags"]["point"], "rows": s["rows"]} for s in run(query)]}

    @tool()
    def query_influxql(query: str, database: str = DB, limit: int = 500) -> dict:
        """Freie InfluxQL-Abfrage: eine SELECT- oder SHOW-Anweisung auf einer freigegebenen Datenbank, Ergebnis gekürzt auf limit Zeilen je Reihe."""
        if database not in DATABASES:
            raise ToolError(f"Erlaubte Datenbanken: {', '.join(DATABASES)}")
        limit = max(1, min(limit, MAX_ROWS))
        series = run(check_query(query), database)
        truncated = any(len(s["rows"]) > limit for s in series)
        return {"truncated": truncated, "series": [s | {"rows": s["rows"][:limit]} for s in series]}

    return mcp


def asgi_app():
    """Stateless ohne Host-Prüfung, davor steht Traefik (nur LAN)."""
    return create().streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


if __name__ == "__main__":
    uvicorn.run(asgi_app(), host="0.0.0.0", port=8000)
