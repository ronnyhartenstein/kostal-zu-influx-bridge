# CLAUDE.md

## Projektüberblick

Docker-Compose-Stack für Telemetrie eines Kostal Plenticore Wechselrichters:
- **Quelle**: Modbus/SunSpec TCP (`MODBUS_PORT=1502`, Unit-ID `71`)
- **Senken**: InfluxDB 1.8 und MQTT (Mosquitto)
- **Bridge**: `app/main.py` — SunSpec-Discovery, CDAB-Decoding, Write/Publish

## Projektstruktur

```
app/main.py              # Einstieg und Abfragezyklus
app/modbus.py, sunspec.py, flat.py, decoders.py  # Quelle und Dekodierung
app/sinks.py             # InfluxSink, LegacyHausSink, MqttSink
app/legacy.py            # Zuordnung und Umrechnung für haus.strom
app/tests/               # Unit-Tests (unittest)
app/requirements.txt     # influxdb, paho-mqtt, pymodbus, PyYAML
app/Dockerfile
spec/                    # Sollzustand: Architektur, Datenmodell, Legacy-Sink, Betrieb
config/registers.yml     # Semantisches Register-Mapping (einzige Exportquelle)
docker-compose.yml       # Bridge + InfluxDB 1.8 + Mosquitto
.env / .env.example      # Alle Konfigurationsparameter
mosquitto/config/        # Broker-Basisconfig
```

## Stack starten & testen

```bash
cp .env.example .env          # einmalig
docker compose up -d --build
docker compose ps             # alle Services healthy?
docker compose logs --tail=100 kostal-bridge
```

Smoke-Tests nach Änderungen:

```bash
# InfluxDB
docker compose exec -T influxdb influx \
  -username "kostal" -password "kostalpass" -database "kostal" \
  -execute "SELECT COUNT(value) FROM kostal_plenticore WHERE time > now() - 2m"

# MQTT
docker compose exec -T mosquitto sh -c \
  "mosquitto_sub -h localhost -p 1883 -t 'home/kostal/plenticore/#' -C 10 -W 8 -v"
```

Unit-Tests (ohne Wechselrichter und Influx):

```bash
docker compose build kostal-bridge
docker compose run --rm --no-deps -v "$PWD/app:/app" kostal-bridge python -m unittest discover -s tests
```

## Kernarchitektur (`app/main.py`)

`KostalBridge` läuft in einer Endlosschleife (`run()`):
1. `_ensure_modbus()` — verbindet/reconnectet bei Verbindungsverlust
2. `_discover_sunspec()` — findet SunSpec-Basis-Adresse (gecacht bis Reconnect)
3. `_collect_points()` — liest alle konfigurierten Modelle aus
4. `_write_influx()` + `_publish_mqtt()` — schreibt Ergebnisse
5. `_touch_heartbeat()` — `/tmp/bridge_heartbeat` für Docker-Healthcheck

**Wichtige Implementierungsdetails:**
- Fallback-Host: `MODBUS_HOST_FALLBACK` wird nach Primary versucht
- SunSpec-Suche: Kandidaten `[40000, 39999, 50000, 0]`; Marker `0x5375, 0x6E53` ("SunS")
- Word-Order für 32-bit: **CDAB** (`cdab_u32()` — bytes C,D,A,B)
- Exportpolicy: **Nur** in `config/registers.yml` definierte Punkte werden publiziert

## InfluxDB-Feldschema

| Python-Typ | Influx-Felder |
|---|---|
| `bool` | `value_bool` |
| `int` | `value_int` + `value` (als float) |
| `float` (finite) | `value` |
| `str` | `value_str` |
| `float` (inf/nan) | wird übersprungen |

Tags pro Messung: `source` (Hostname), `model` (`m<id>`), `point` (Feldname), `unit` (optional)
Measurement-Name: `INFLUX_MEASUREMENT` (Default: `kostal_plenticore`)

## Retention & Downsampling

Die Bridge schreibt ohne RP-Angabe immer in die Default-RP `autogen`. Drei Retention Policies + zwei Continuous Queries (eingerichtet via `influxdb/init/001-retention-downsampling.sh`) verdichten die Historie stufenweise:

| RP | Auflösung | Aufbewahrung | Quelle |
|---|---|---|---|
| `autogen` (Default) | roh (`POLL_INTERVAL`) | 1 Tag | Bridge-Writes |
| `rp_1min` | 1-Min-Mittelwert | 7 Tage | CQ `cq_1min` aus `autogen` |
| `rp_5min` | 5-Min-Mittelwert | unbegrenzt | CQ `cq_5min` aus `rp_1min` |

Numerische Felder (`value`, `value_int`) werden per `mean()` verdichtet, `value_bool`/`value_str` per `last()`. Grafana-Zeitreihen-Panels lesen deshalb per Comma-`FROM` über alle drei RPs (`"autogen"."<measurement>", "rp_1min"."<measurement>", "rp_5min"."<measurement>"`), damit ältere Zeiträume weiterhin Daten zeigen.

Das Init-Skript läuft bei einem **frischen** InfluxDB-Volume automatisch (`docker-entrypoint-initdb.d`). Bei einem bereits bestehenden Volume einmalig manuell nachziehen:

```bash
docker compose cp influxdb/init/001-retention-downsampling.sh influxdb:/tmp/bootstrap.sh
docker compose exec influxdb sh /tmp/bootstrap.sh
docker compose exec -T influxdb influx -username "kostal" -password "kostalpass" -database "kostal" -execute "SHOW RETENTION POLICIES ON kostal"
```

## Legacy-Sink `haus.strom`

Übergangslösung für die NodeRED-Ablösung (docker-mini#44), Standard aus (`LEGACY_HAUS_ENABLED=false`). Schreibt 7 Reihen formatgleich zu NodeRED, bis die Dashboards auf `kostal` umgestellt sind. Fehler im Sink werden nur geloggt und dürfen den Zyklus nicht abbrechen. Details: `spec/legacy-sink.md`.

## MQTT-Schema

Topic: `${MQTT_TOPIC_PREFIX}/m<model>/<point>`

- Numerische Werte: direkt als String (`"123.4"`)
- Strings/Sonstige: JSON `{"value": ..., "ts": ..., "unit": ...}`

## `config/registers.yml` erweitern

```yaml
models:
  "103":           # Modell-ID als String-Key
    points:
      - name: ac_wirkleistung_gesamt_w   # snake_case, Einheitssuffix
        offset: 0                         # Register-Offset im Datenblock
        type: i16                         # u16 | i16 | u32_cdab | i32_cdab | f32_cdab | string
        scale_from: 13                    # optional: Offset des SF-Registers (10^SF)
        unit: W                           # optional
        enum_map:                         # optional: {str(value): label}
          "0": "Standby"
        length: 16                        # nur bei type: string (Zeichenanzahl)
```

**Bekannte SunSpec-Modelle am Kostal Plenticore:**
`m1` (Common), `m103` (AC Inverter 3-ph), `m113` (Float-Inverter), `m120` (Nameplate), `m123` (Control), `m160` (DC-Strings), `m802` (Kostal proprietär)

## Entwicklungsprinzipien

- **Read-only**: Keine Schreibzugriffe auf Wechselrichter-Register.
- **Additive Env-Keys**: Neue `.env`-Variablen nur hinzufügen, nie bestehende Keys umbenennen.
- **Stabile Feld-/Topic-Namen**: Breaking Changes nur mit expliziter Migrationsnotiz.
- **Semantische Namen**: Deutsch, `snake_case`, Einheitssuffix — z. B. `ac_wirkleistung_gesamt_w`.
- **Kein generischer Export**: Nie rohe `r<offset>_*`-Werte exportieren; immer über `registers.yml`.
- **Fehlertoleranz**: Einzelne Punkt-Decode-Fehler per `logger.debug` überspringen, nicht abbrechen.

## Nicht-Ziele

- Kein Schreibkanal zurück zum Wechselrichter
- Kein TLS/Auth/Secrets-Hardening im Repo-Default
- Kein garantierter Feldkatalog ohne `registers.yml`-Mapping
