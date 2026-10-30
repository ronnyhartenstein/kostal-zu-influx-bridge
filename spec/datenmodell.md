# Datenmodell

## Registermapping

`config/registers.yml` ist die einzige Exportquelle: `models` für SunSpec-Modelle, `flat_registers` für absolute
Holding-Register. Punktnamen: Deutsch, `snake_case`, Einheitssuffix (`ac_wirkleistung_gesamt_w`).
32-Bit-Werte sind CDAB-kodiert, das Low-Word steht an der niedrigeren Adresse. Ausnahmen mit Typ `u32_abcd`
(High-Word zuerst): `U32`-Register im Block ab 512 und die 32-Bit-Punkte der SunSpec-Modelle, obwohl Register 5 CDAB
meldet. Beleg: Register 529 liefert `0000 3146`, also 12614, passend zum Float-Wert in Register 1068.
Geprüft live am PLENTICORE plus 8.5 mit UI 01.30.12092, MC/IOC 01.80 und HW 0200 gegen die Kostal-Schnittstellendoku
Rev. 2.7. Diese nennt die Abweichung nicht, nach einem Firmware-Update die Wortreihenfolge daher erneut prüfen.

In SunSpec-Modellen werden die Marker für „nicht belegt“ nicht geschrieben: `0xFFFF` (u16), `0x8000` (i16),
`0xFFFFFFFF` (u32), `0x80000000` (i32) und Punkte, deren Scale Factor `0x8000` ist. `0xFFFE` ist kein Marker, sondern
der Scale Factor −2. Für `flat_registers` gelten die Marker nicht.

## Batterie

Verbaut ist eine BYD HVM mit 4 Modulen zu je 2,76 kWh, also 11,04 kWh Nennenergie und 64 Zellen in Reihe.
Der WR liefert die reale Kapazität nicht. Für Energieinhalte gilt der Wert von rund 9,5 kWh, er stammt nicht aus einem
Register.

| Quelle | Wert | Einordnung |
|---|---|---|
| Register 1068, 529, `m802` Offset 1 | 12614 Wh | Rechenwert: 54 Ah Nennladung × 233,6 V (64 × 3,65 V Ladeschluss), nicht exportiert |
| Register 512, `m802` Offset 0 | 49 Ah | `batterie_bruttokapazitaet_ah`; Herkunft im BMS unbelegt, keine Energieangabe |
| 49 Ah × 207 V (mittlere Entladespannung) | ca. 10,1 kWh | nur Abschätzung |
| Register 1046/1048 je SoC-Hub | Median 9,6 kWh | gemessen über 15 Lade- und Entladephasen ab 20 % Hub, 23.–30.10.2026, Spanne 7,0–11,2 kWh |

`m120` ist laut SunSpec das Nameplate-Modell des Wechselrichters (`VARtg` = 8500 VA). `WHRtg` und `AhrRtg` stehen dort
auf 0, es enthält keine Batteriewerte.

## Migration Batteriewerte (30.10.2026)

Die Blöcke `m120` und `m802` waren falsch zugeordnet: Alle Punkte in `m120` und alle `m802`-Punkte unterhalb von
Offset 62 lasen fremde Register, ab Offset 62 las das Mapping über das Modellende hinaus und lieferte nichts. Wer
Altdaten dieser Reihen auswertet, darf sie nicht als Messwerte lesen. Ohne `model`-Filter können die alten
`m802`-Reihen namensgleiche `flat`-Werte überlagert haben, z. B. `tagesertrag_wh`.

| Punkt | Änderung |
|---|---|
| `flat/batterie_bruttokapazitaet_ah` | Wert korrigiert: 49 statt 3211264 |
| `flat/batterie_nutzbare_kapazitaet_wh` | entfernt, siehe Abschnitt Batterie |
| `m120/*` | entfernt |
| `m802/*` | ersetzt durch SoC, Spannung, Strom, Leistung und Zyklen; Namen bleiben, Werte sind jetzt korrekt |

Batteriestrom und -leistung in `m802` sind beim Entladen positiv, wie Register 200.

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
