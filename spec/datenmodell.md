# Datenmodell

## Registermapping

`config/registers.yml` ist die einzige Exportquelle: `models` für SunSpec-Modelle, `flat_registers` für absolute
Holding-Register. Punktnamen: Deutsch, `snake_case`, Einheitssuffix (`ac_wirkleistung_gesamt_w`).
32-Bit-Werte sind CDAB-kodiert, das Low-Word steht an der niedrigeren Adresse.

## InfluxDB

Measurement `INFLUX_MEASUREMENT` (Default `kostal_plenticore`), Zeitstempel sekundengenau.

Tags: `source` (aktiver Modbus-Host), `model` (`m<id>` oder `flat`), `point`, `unit` (optional).

| Python-Typ | Felder |
|---|---|
| `bool` | `value_bool` |
| `int` | `value_int` und `value` (float) |
| `float`, endlich | `value` |
| `float`, inf/nan | wird übersprungen |
| `str` | `value_str` |

## Retention im Repo-Stack

Eingerichtet durch `influxdb/init/001-retention-downsampling.sh`:

| RP | Auflösung | Aufbewahrung |
|---|---|---|
| `autogen` (Default) | roh | 1 Tag |
| `rp_1min` | 1-Min-Mittel | 7 Tage |
| `rp_5min` | 5-Min-Mittel | unbegrenzt |

Numerische Felder werden per `mean()`, `value_bool` und `value_str` per `last()` verdichtet.
Auf Mini gelten Retention und Downsampling aus `docker-mini`, nicht diese Tabelle.

## MQTT

Topic: `${MQTT_TOPIC_PREFIX}/<model>/<point>`

- Zahlen: Wert als String, z. B. `123.4`
- Sonstige: JSON `{"value": ..., "ts": ..., "unit": ...}`
