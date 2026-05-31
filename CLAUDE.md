# CLAUDE.md

## Projektüberblick

Docker-Compose-Stack für Telemetrie eines Kostal Plenticore Wechselrichters:
- **Quelle**: Modbus/SunSpec TCP (`MODBUS_PORT=1502`, Unit-ID `71`)
- **Senken**: InfluxDB 1.8 und MQTT (Mosquitto)
- **Bridge**: `app/main.py` — SunSpec-Discovery, CDAB-Decoding, Write/Publish

## Projektstruktur

```
app/main.py              # Kernlogik (KostalBridge-Klasse)
app/requirements.txt     # influxdb, paho-mqtt, pymodbus, PyYAML
app/Dockerfile
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
