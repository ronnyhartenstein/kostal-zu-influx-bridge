# InfluxDB Retention & Downsampling einrichten

## Context

Aktuell pollt die Bridge alle `POLL_INTERVAL=5` Sekunden (`app/main.py:39`) und schreibt bei jedem Zyklus einen Batch nach InfluxDB (`app/sinks.py:76`). Es existiert **keine** Retention Policy — die Datenbank `kostal` läuft unter der automatisch erzeugten Default-RP `autogen` mit `DURATION 0s` (unbegrenzt). Bei 5s-Auflösung über viele Punkte/Modelle wächst die DB entsprechend schnell und unbegrenzt.

Ziel: Rohdaten (5s) nur 1 Tag vorhalten, danach automatisch auf 1-Minuten-Mittelwerte verdichten (7 Tage), danach auf 5-Minuten-Mittelwerte (unbegrenzt). Das reduziert den Langzeit-Speicherbedarf um ~60x (5s→5min) bei weiterhin durchgehend verfügbarer Historie.

Da die bestehenden Grafana-Dashboards (`grafana/dashboards/energiefluss.json`, `ertraege.json`) ihre Zeitreihen-Panels ohne explizite RP-Angabe abfragen (`FROM "kostal_plenticore"` → trifft nur die Default-RP), würden sie nach der Verkürzung von `autogen` auf 1 Tag für größere Zeiträume leer laufen. Deshalb werden die betroffenen Panel-Queries mit angepasst, sodass sie über alle drei RPs hinweg lesen.

## Implementierung

### 1. Retention Policies + Continuous Queries (neues Init-Skript)

Neue Datei `influxdb/init/001-retention-downsampling.sh` (ausführbar), die per `influx -execute` folgendes einrichtet:

- `ALTER RETENTION POLICY "autogen" ON "<db>" DURATION 1d REPLICATION 1 DEFAULT` (Rohdaten bleiben Default-RP, aber nur noch 1 Tag statt unbegrenzt — Bridge-Writes ändern sich nicht, da kein RP im Write-Call angegeben wird)
- `CREATE RETENTION POLICY "rp_1min" ON "<db>" DURATION 7d REPLICATION 1`
- `CREATE RETENTION POLICY "rp_5min" ON "<db>" DURATION 0s REPLICATION 1` (unbegrenzt)
- `CREATE CONTINUOUS QUERY "cq_1min" ...` — liest aus `autogen.<measurement>`, schreibt nach `rp_1min.<measurement>`, `GROUP BY time(1m), "source", "model", "point", "unit"`, mit `mean(value)`, `mean(value_int)`, `last(value_bool)`, `last(value_str)` (numerische Felder werden gemittelt, Text/Bool behält den letzten Wert im Fenster). `RESAMPLE EVERY 1m FOR 2m` für etwas Toleranz bei kurzen Ausfällen.
- `CREATE CONTINUOUS QUERY "cq_5min" ...` — analog, liest aus `rp_1min`, schreibt nach `rp_5min`, `GROUP BY time(5m), ...`, `RESAMPLE EVERY 5m FOR 10m`.

Das Skript nutzt `$INFLUXDB_DB`, `$INFLUXDB_ADMIN_USER`, `$INFLUXDB_ADMIN_PASSWORD` (bereits im influxdb-Container gesetzt) sowie neu `$INFLUX_MEASUREMENT` (Fallback `kostal_plenticore`).

### 2. `docker-compose.yml` (influxdb-Service)

- `INFLUX_MEASUREMENT: ${INFLUX_MEASUREMENT}` zur `environment:`-Liste hinzufügen (additiver Pass-through, keine bestehenden Keys ändern)
- Volume-Mount ergänzen: `./influxdb/init:/docker-entrypoint-initdb.d:ro`
  - Wichtig: Dieses Verzeichnis wird vom offiziellen `influxdb`-Image **nur beim allerersten Start mit leerem Datenverzeichnis** automatisch ausgeführt. Für den bestehenden, bereits befüllten Stack greift das nicht rückwirkend — siehe Schritt 4 (manueller Bootstrap).

### 3. Grafana-Dashboard-Queries anpassen

In `grafana/dashboards/energiefluss.json` und `ertraege.json`: alle Panel-Queries, die `$timeFilter` + `GROUP BY time($__interval)` verwenden (Zeitreihen-Panels — 6 in energiefluss.json, 6 in ertraege.json), von

```
FROM "kostal_plenticore" WHERE (...) AND $timeFilter GROUP BY time($__interval) fill(null)
```

auf Comma-FROM über alle drei RPs umstellen:

```
FROM "autogen"."kostal_plenticore", "rp_1min"."kostal_plenticore", "rp_5min"."kostal_plenticore" WHERE (...) AND $timeFilter GROUP BY time($__interval) fill(null)
```

Die reinen `last(value)`-Stat-Panels (ohne `$timeFilter`, z. B. aktuelle Leistung/SoC) bleiben unverändert — sie greifen ohnehin auf die aktuellsten (rohen) Daten in `autogen` zu.

### 4. CLAUDE.md dokumentieren

Neuer Abschnitt "Retention & Downsampling" (nach "InfluxDB-Feldschema"): kurze Beschreibung der drei RPs (`autogen` 1d, `rp_1min` 7d, `rp_5min` unbegrenzt) und der beiden CQs, plus der einmalige manuelle Bootstrap-Befehl für bestehende Deployments (siehe Verifikation).

## Verifikation

1. `docker compose up -d --build` — übernimmt die geänderte `INFLUX_MEASUREMENT`-Env-Variable im influxdb-Service (Container wird neu erstellt, Volume/Daten bleiben erhalten).
2. Einmaligen Bootstrap für die **bestehende** DB manuell anstoßen (da `docker-entrypoint-initdb.d` nicht erneut läuft):
   ```
   docker compose cp influxdb/init/001-retention-downsampling.sh influxdb:/tmp/bootstrap.sh
   docker compose exec influxdb sh /tmp/bootstrap.sh
   ```
3. RPs prüfen:
   ```
   docker compose exec -T influxdb influx -username kostal -password kostalpass -database kostal -execute "SHOW RETENTION POLICIES ON kostal"
   ```
   Erwartet: `autogen` (1d, default), `rp_1min` (7d), `rp_5min` (0s = unbegrenzt).
4. CQs prüfen: `SHOW CONTINUOUS QUERIES` → `cq_1min`, `cq_5min` vorhanden.
5. Nach einigen Minuten warten und downgesampelte Daten prüfen:
   ```
   docker compose exec -T influxdb influx -username kostal -password kostalpass -database kostal -execute 'SELECT COUNT(value) FROM "rp_1min"."kostal_plenticore" WHERE time > now() - 10m'
   ```
6. Grafana öffnen (`energiefluss`, `ertraege`), Zeiträume 1h / 7d / 30d durchklicken — Panels müssen durchgehend Daten zeigen, keine Query-Fehler.
