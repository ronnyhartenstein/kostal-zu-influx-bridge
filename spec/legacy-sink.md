# Legacy-Sink `haus.strom`

**Zweck:** Übergang für die NodeRED-Ablösung (docker-mini#44). Fünf Grafana-Dashboards und die Continuous Queries
lesen die alten Reihen mit Verlauf seit 12/2021. Die Bridge schreibt sie formatgleich weiter, bis die Dashboards
auf `kostal` umgestellt sind. Danach wird der Sink abgeschaltet und entfernt.

## Konfiguration

| Variable | Default | Bedeutung |
|---|---|---|
| `LEGACY_HAUS_ENABLED` | `false` | Sink aktivieren |
| `LEGACY_HAUS_DB` | `haus` | Ziel-Datenbank |
| `LEGACY_HAUS_MEASUREMENT` | `strom` | Ziel-Measurement |

Host, Port, Login und SSL kommen von `INFLUX_*`. Geschrieben wird in die Default-RP der Datenbank.
Die Datenbank muss existieren, der Sink legt sie nicht an.

## Format

Ein Tag `site_name`, ein Feld `value` (immer float), keine weiteren Tags. Zeitstempel sekundengenau.

```
strom,site_name=pv_production value=0.536 1793352000000000000
```

## Zuordnung

| `site_name` | Register | Bridge-Punkt | Umrechnung |
|---|---|---|---|
| `pv_production` | 172 | `ac_wirkleistung_gesamt_w` | W / 1000 |
| `own_use_from_pv` | 116 | `hausverbrauch_pv_w` | W / 1000 |
| `own_use_from_battery` | 106 | `hausverbrauch_batterie_w` | W / 1000 |
| `own_use_from_grid` | 108 | `hausverbrauch_netz_w` | W / 1000 |
| `total_power` | 252 | `netzleistung_gesamt_w` | W / 1000, mit Vorzeichen |
| `total_home_consumption` | 252 | `netzleistung_gesamt_w` | W / 1000, mit Vorzeichen |
| `battery_capacity` | 514 | `batterie_soc_prozent_int` | SoC × 0,095 |

Alle Werte werden im Zielformat auf 4 Nachkommastellen gerundet und jeden Zyklus geschrieben.

## Eigenheiten der alten Reihen

Diese Werte sind fachlich schief, bleiben für den durchgehenden Verlauf aber absichtlich so:

- `pv_production` ist die AC-Wirkleistung des Wechselrichters, nicht die DC-PV-Leistung.
- `total_home_consumption` ist derselbe Wert wie `total_power`, also die Netzleistung.
- `battery_capacity` ist SoC × 0,095 (SoC 16 % → 1,52).

Abweichungen zu NodeRED: Takt 5 s statt 3 s (Batterie jeden Zyklus statt 1×/min). NodeRED rundet die Watt-Werte vor
der Division und `battery_capacity` gar nicht. Beides ist für `mean`, `min`, `max` und `integral` unerheblich.

## Fehlerfälle

- Wert fehlt, ist nicht numerisch oder nicht endlich: für diesen `site_name` nichts schreiben, weder 0 noch NaN.
- Schreibfehler: `warning`-Log, der Zyklus läuft weiter. Die Werte dieses Zyklus fehlen in `haus.strom`.

## Umschalten

Den Sink erst aktivieren, wenn gleichzeitig die `influxdb out`-Ausgänge in NodeRED abgeschaltet werden, sonst
schreiben beide in dieselben Reihen. Das Vorgehen steht in docker-mini#44.
