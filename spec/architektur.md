# Architektur

```
Kostal Plenticore ── Modbus TCP ──> kostal-bridge ──> InfluxDB (DB kostal)
                                         │  └───────> InfluxDB (DB haus, optional, Legacy-Sink)
                                         └──────────> MQTT
```

| Modul | Aufgabe |
|---|---|
| `app/main.py` | Konfiguration laden, Abfragezyklus |
| `app/modbus.py` | Verbindung mit Primary- und Fallback-Host |
| `app/sunspec.py` | SunSpec-Discovery, Modelle lesen |
| `app/flat.py` | Direkte Register aus `flat_registers` lesen (Model `flat`) |
| `app/decoders.py` | Dekoder, `DecodedPoint` |
| `app/sinks.py` | `InfluxSink`, `LegacyHausSink`, `MqttSink` |
| `app/legacy.py` | Zuordnung und Umrechnung für den Legacy-Sink |

Im Compose-Stack des Repos laufen zusätzlich `influxdb`, `mosquitto`, `grafana` und `web` als lokale Testumgebung.

## Abfragezyklus

Alle `POLL_INTERVAL` Sekunden (Default 5):

1. Modbus-Verbindung sicherstellen, bei neuer Verbindung SunSpec-Cache verwerfen
2. SunSpec-Modelle und `flat_registers` lesen
3. Nach `kostal` schreiben
4. Legacy-Sink schreiben, falls aktiv
5. Per MQTT publizieren
6. Heartbeat `/tmp/bridge_heartbeat` aktualisieren (Docker-Healthcheck: jünger als 60 s)

## Fehlerverhalten

| Fehler | Verhalten |
|---|---|
| Einzelner Punkt nicht dekodierbar | Punkt überspringen, `debug`-Log |
| Flat-Batch nicht lesbar | Punkte dieses Batches fehlen im Zyklus, `warning`-Log |
| Fehler in Modbus, `kostal` oder MQTT | Zyklus abbrechen, Modbus zurücksetzen, kein Heartbeat in diesem Zyklus |
| Fehler im Legacy-Sink | `warning`-Log, Zyklus läuft normal weiter |
