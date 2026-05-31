# Plan: Flat-Modbus-Interface (absolute Register) parallel zum SunSpec-Interface

## Hintergrund

Der Kostal PLENTICORE plus unterstützt **zwei parallele Modbus-Interfaces** auf Port 1502 / Unit-ID 71:

| Interface | Adressierung | Typen | Skalierung |
|---|---|---|---|
| **SunSpec** (aktuell) | Modell-Relative Offsets (Discovery nötig) | u16/i16/u32/f32 gemischt | Scale-Factor-Register |
| **Flat Kostal** (neu) | Absolute Halte-Register (2, 56, 98, 106 …) | Fast alles Float32 CDAB | Keine (Werte direkt in SI) |

Das Flat-Interface liefert einige **wichtige Werte, die im SunSpec-m802-Modell fehlen** (oder deren Offsets unbekannt sind):

- Register 106: Hausverbrauch aus Batterie (W)
- Register 108: Hausverbrauch aus Netz (W)
- Register 116: Hausverbrauch direkt aus PV (W)
- Register 118: Gesamter Hausverbrauch kumuliert (Wh)
- Register 252: Gesamte Wirkleistung Netzzähler (W) — Vorzeichen: negativ = Einspeisung
- Register 104: Status Energiemanager (UInt32: 0=Idle, 2=Notladung, 8/16=Winterbetrieb)
- Register 98: Platinen-Temperatur Steuerung (°C)
- Register 320/322/324/326: Gesamt-/Tages-/Jahres-/Monatsertrag AC (Wh)
- Register 514: Batterie-SoC Ganzzahl (%)
- Register 512: Batterie-Bruttokapazität (Ah)

## Ziel

Die Bridge soll beide Interfaces parallel bedienen können, sodass Werte aus dem Flat-Interface neben den SunSpec-Werten in InfluxDB und MQTT landen.

## Lösungsansatz

### Option A — Eigenständiger "Flat"-Collector in `app/main.py` (empfohlen)

1. `config/registers.yml` um einen neuen Top-Level-Key `flat_registers` erweitern:
   ```yaml
   flat_registers:
     - name: hausverbrauch_aus_batterie_w
       address: 106        # absolute Halte-Register-Adresse
       type: f32_cdab
       unit: W
     - name: hausverbrauch_aus_netz_w
       address: 108
       type: f32_cdab
       unit: W
     - name: hausverbrauch_aus_pv_w
       address: 116
       type: f32_cdab
       unit: W
     - name: netzleistung_gesamt_w
       address: 252
       type: f32_cdab
       unit: W
     # … weitere
   ```

2. `KostalBridge._collect_points()` um eine Methode `_collect_flat_points()` ergänzen:
   - Gruppiert die konfigurierten `flat_registers` nach zusammenhängenden Adressbereichen
   - Liest per `read_holding_registers(address, count)` — ohne SunSpec-Basis-Offset
   - Dekodiert alle Werte als `f32_cdab` (oder u16/u32 je nach Konfiguration)
   - Gibt die gleiche `[(measurement, tags, fields)]`-Struktur zurück wie `_collect_points()`

3. Tags für Flat-Register-Punkte: `source=<hostname>`, `model=flat`, `point=<name>`, `unit=<unit>`

4. Keine SunSpec-Discovery nötig — direkte Adresse.

### Option B — Separater zweiter Stack-Service

Ein eigenständiger `flat-bridge`-Container der nur die absoluten Register liest. Mehr Overhead, einfacheres Deployment-Testing. Nicht empfohlen, weil doppelte Modbus-Verbindung die begrenzte Connection-Kapazität des Geräts stärker belastet.

## Wichtige Implementierungsdetails

- **Endianness**: Flat-Interface nutzt CDAB (Little-Endian Word-Swap) — identisch zur bestehenden `cdab_u32()`-Logik.
- **Adress-Batching**: Zusammenhängende Register in einem `read_holding_registers()`-Call bündeln (max. ~50 Register/Call), um die Verbindung zu schonen.
- **Float-Decode**: `struct.unpack('>f', bytes([C, D, A, B]))` — identisch zur bestehenden CDAB-Logik.
- **Connection-Limit**: Das G1 SCB unterstützt nur wenige parallele TCP-Verbindungen. Flat- und SunSpec-Reads müssen dieselbe pymodbus-Verbindung nutzen.
- **Measurement-Name**: Flat-Punkte landen im selben `INFLUX_MEASUREMENT` wie SunSpec-Punkte — nur der Tag `model=flat` unterscheidet sie.

## Neue Register für `flat_registers` (aus Gemini-Recherche)

| Adresse | Name (Vorschlag) | Typ | Einheit | Notiz |
|---|---|---|---|---|
| 98 | platinen_temperatur_c | f32_cdab | °C | |
| 104 | energiemanager_status | u32_cdab | — | 0=Idle, 2=Notladung |
| 106 | hausverbrauch_batterie_w | f32_cdab | W | |
| 108 | hausverbrauch_netz_w | f32_cdab | W | |
| 110 | hausverbrauch_batterie_gesamt_wh | f32_cdab | Wh | kumuliert |
| 112 | hausverbrauch_netz_gesamt_wh | f32_cdab | Wh | kumuliert |
| 114 | hausverbrauch_pv_gesamt_wh | f32_cdab | Wh | kumuliert |
| 116 | hausverbrauch_pv_w | f32_cdab | W | |
| 118 | hausverbrauch_gesamt_wh | f32_cdab | Wh | kumuliert |
| 172 | ac_wirkleistung_gesamt_w | f32_cdab | W | |
| 252 | netzleistung_gesamt_w | f32_cdab | W | negativ = Einspeisung |
| 320 | gesamtertrag_wh | f32_cdab | Wh | |
| 322 | tagesertrag_wh | f32_cdab | Wh | |
| 514 | batterie_soc_prozent_int | u16 | % | Ganzzahl |

## Betroffene Dateien

- `config/registers.yml` — neuer Top-Level-Key `flat_registers`
- `app/main.py` — `_collect_flat_points()`, Integration in `run()`-Schleife, YAML-Parsing erweitern

## Verifikation

```bash
docker compose up -d --build
docker compose exec -T mosquitto sh -c \
  "mosquitto_sub -h localhost -p 1883 -t 'home/kostal/plenticore/flat/#' -C 10 -W 8 -v"
# Erwarte: home/kostal/plenticore/flat/hausverbrauch_netz_w -> "345.2"
```

InfluxDB-Check:
```bash
docker compose exec -T influxdb influx \
  -username "kostal" -password "kostalpass" -database "kostal" \
  -execute "SELECT * FROM kostal_plenticore WHERE model='flat' LIMIT 5"
```
