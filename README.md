# kostal-zu-influx

Lokaler Docker-Compose Stack für Telemetrie von einem Kostal Plenticore:

- Quelle: Modbus/SunSpec (TCP, Port `1502`)
- Senken: InfluxDB 1.8 und MQTT (Mosquitto)
- Bridge: Python-Service mit SunSpec-Discovery, CDAB-Decoding und Publish pro Messwert

## Architektur

- `kostal-bridge`: liest WR-Daten, dekodiert Register, schreibt nach Influx und MQTT
- `influxdb`: Zeitreihenziel für Messwerte
- `mosquitto`: MQTT-Broker für Live-Verteilung der Messwerte

Topic-Schema:

- `${MQTT_TOPIC_PREFIX}/m<model>/<point>`

Beispiel:

- `home/kostal/plenticore/m1/r0_u16`

## Schnellstart

1. Konfiguration erzeugen:

```bash
cp .env.example .env
```

2. Stack bauen und starten:

```bash
docker compose up -d --build
```

3. Status prüfen:

```bash
docker compose ps
docker compose logs -f kostal-bridge
```

## Relevante Defaults

- `MODBUS_HOST=kostal-wr.home`
- `MODBUS_HOST_FALLBACK=192.168.178.53`
- `MODBUS_PORT=1502`
- `MODBUS_UNIT_ID=71`
- `MODBUS_WORD_ORDER=CDAB`
- `INFLUX_HOST=influxdb`
- `MQTT_HOST=mosquitto`
- `MQTT_QOS=0`
- `MQTT_RETAIN=false`

## Funktionstest

Influx: Daten angekommen?

```bash
docker compose exec -T influxdb influx \
  -username "kostal" -password "kostalpass" -database "kostal" \
  -execute "SELECT COUNT(value) FROM kostal_plenticore WHERE time > now() - 2m"
```

MQTT: Live-Werte sichtbar?

```bash
docker compose exec -T mosquitto sh -c \
  "mosquitto_sub -h localhost -p 1883 -t 'home/kostal/plenticore/#' -C 10 -W 8 -v"
```

## Betrieb

Stoppen:

```bash
docker compose down
```

Stoppen inkl. Volumes (löscht lokale Influx-Testdaten):

```bash
docker compose down -v
```

## Erweiterungen

- Optionales Register-Mapping: `config/registers.yml`
- Bridge-Logik: `app/main.py`
- Abhängigkeiten: `app/requirements.txt`

Hinweis:

- Aktuell ist bereits ein semantisches deutsches PV-Mapping für SunSpec `Model 103` enthalten (z. B. `ac_wirkleistung_gesamt_w`, `netzfrequenz_hz`, `dc_leistung_gesamt_w`).
- Zusätzlich werden weiterhin generische Punkte exportiert (`r<offset>_u16`, `r<offset>_u32_cdab`, `r<offset>_i32_cdab`, `r<offset>_f32_cdab`).
