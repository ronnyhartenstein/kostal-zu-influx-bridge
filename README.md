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

## Gefundene SunSpec-Modelle (Kostal Plenticore)

Im aktuellen Live-Test wurden diese Modelle entdeckt:

- `m1`: Common Model (Geräteinformationen)
- `m103`: Inverter (3-phasig, AC/DC-Leistungswerte)
- `m113`: Erweiterte Inverter-Daten (herstellerabhängig)
- `m120`: Nameplate/Nennwerte
- `m123`: Status-/Control-naher Inverter-Block
- `m160`: Erweiterte DC-/PV-Kanalwerte
- `m802`: Kostal-spezifisches (proprietäres) Modell

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

- Das Mapping wird aus `config/registers.yml` gelesen.
- Es werden nur konfigurierte Punkte exportiert (keine generischen `r<offset>_*` Werte).
- Das aktuelle Mapping basiert auf `research_kostal-modbus-sunspec.md`.

## Vorschläge für weiteres Mapping

Priorität für den nächsten Ausbau:

1. `m802` (Kostal proprietär): Batteriespeicher, Hausverbrauch, Netzbezug, Netzeinspeisung, Tagesertrag
2. `m160`: PV-String/Tracker-Werte als `pv_string_1_spannung_v`, `pv_string_1_strom_a`, `pv_string_1_leistung_w` usw.
3. `m123` / `m113`: Betriebszustände und Fehlercodes in deutsche Klartext-Statusfelder (inkl. Enum-Mapping)
4. Status-Topics zusätzlich als menschenlesbare Texte, z. B. `betriebszustand_text`
5. Semantische Felder mit plausiblen Skalierungs-/Typchecks absichern (Quality Gates)

## TODOs

- [ ] **Energiefluss-Aufschlüsselung in m802 ergänzen:** NodeRED liest über native Register
  `own_use_from_battery` (Reg 106) und `own_use_from_pv` (Reg 116) als separate Werte.
  Im aktuellen SunSpec-Mapping fehlen diese — nur `hausverbrauch_gesamt_w` (Summe, Offset 80)
  ist vorhanden. Die korrekten SunSpec-Offsets für die Aufschlüsselung nach Quelle müssen
  per Live-Messung oder Kostal-Dokumentation ermittelt und dann als
  `eigenverbrauch_aus_batterie_w` und `eigenverbrauch_aus_pv_w` in m802 eingetragen werden.
