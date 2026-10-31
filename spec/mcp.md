# MCP-Server

`mcp/server.py` gibt Claude lesenden Zugriff auf die Messdaten in InfluxDB. Der Dienst `kostal-mcp` ist Teil dieses
Projekts; Installationen wie `docker-mini` betreiben ihn nur und stellen ihn per Umgebung ein. Er spricht nie mit dem
Wechselrichter.

- **Endpunkt:** `/mcp`, Streamable HTTP, stateless, Port 8000 im Container (`MCP_PORT` im Repo-Stack, Default 8090).
- **Zugriff:** kein Token, gedacht nur fürs LAN, wie der Influx-Port selbst.

| Variable | Default | Bedeutung |
|---|---|---|
| `INFLUX_HOST`, `INFLUX_PORT`, `INFLUX_DB`, `INFLUX_USER`, `INFLUX_PASS`, `INFLUX_MEASUREMENT` | wie Bridge | Quelle |
| `BRIDGE_CONFIG` | `/config/registers.yml` | Punktliste für `list_points` |
| `MCP_DATABASES` | `INFLUX_DB` | für `query_influxql` freigegebene Datenbanken, kommagetrennt |
| `MCP_NOTES` | leer | Hinweise der Installation, werden an die Server-Anweisungen gehängt, z. B. Datenlücken |

## Tools

| Tool | Zweck |
|---|---|
| `get_overview` | Datenbanken, Aufbewahrung, jüngster Messpunkt |
| `list_points` | Punkte aus `registers.yml` mit Modell und Einheit |
| `get_latest` | jüngste Werte der letzten Stunde |
| `get_history` | Zeitreihen numerischer Punkte, höchstens 2000 Werte je Punkt |
| `query_influxql` | freie `SELECT`/`SHOW`-Abfrage |

## Datenstufen

`get_history` liest `SHOW RETENTION POLICIES` und nimmt die gröbste Stufe, die fein genug ist und bis zum Startzeitpunkt
zurückreicht. Tagesgrenzen gelten in `Europe/Berlin`.

| Erkannt an | Stufen |
|---|---|
| `rp_5min` (Stack aus diesem Repo) | `autogen`, `rp_1min`, `rp_5min`, Feld `value` |
| `downsample` (Mini) | `autogen`, `downsample` mit `mean_value_5m`, `min_value_5m`, `max_value_5m` |
| sonst | nur `autogen` |

Im Repo-Stack liefern `min` und `max` über verdichtete Stufen Extremwerte der Mittelwerte, nicht der Rohdaten.

## Nur lesend

Abfragen laufen per HTTP-GET, darüber nimmt InfluxDB weder `SELECT INTO` noch `CREATE`, `DROP` oder `DELETE` an.
Zusätzlich lässt der Server nur eine einzelne `SELECT`- oder `SHOW`-Anweisung ohne `INTO` durch.
