# AGENTS.md

Leitfaden für künftige Erweiterungen dieses Projekts.

## Zielbild

- Modbus/SunSpec vom Kostal WR robust einlesen.
- Werte konsistent nach InfluxDB 1.8 und MQTT publizieren.
- Änderungen sollen rückwärtskompatibel zu bestehender `.env` bleiben.

## Projektstruktur

- `docker-compose.yml`: Orchestrierung (bridge + influx + mosquitto)
- `app/main.py`: Kernlogik (Connect, Discovery, Decode, Write/Publish)
- `config/registers.yml`: optionales semantisches Register-Mapping
- `.env.example`: Referenz aller Konfigurationsparameter
- `mosquitto/config/mosquitto.conf`: Broker-Basisconfig

## Entwicklungsprinzipien

- Keine Schreibzugriffe auf Wechselrichter-Register (read-only Telemetrie).
- Bei neuen Features zuerst bestehende Env-Keys respektieren, neue Keys nur additiv.
- Fehler robust behandeln (Retry, Reconnect, keine Endlosschleifen mit hohem Log-Spam).
- Topic- und Feldnamen stabil halten; Breaking Changes nur mit klarer Migrationsnotiz.
- Semantische Namen bevorzugt in gut lesbarem Deutsch als `snake_case` mit Einheitssuffix, z. B. `ac_wirkleistung_gesamt_w`.

## SunSpec/Decoding-Regeln

- Word-Order für 32-bit Werte ist `CDAB` (laut Projektannahme).
- Discovery muss fehlertolerant sein; falls Discovery fehlschlägt, sauber loggen und retryen.
- Bei neuen dekodierten Feldern auf Typkonsistenz achten:
  - Influx: numerische Werte als `value`/`value_int`, Strings als `value_str`
  - MQTT: primitive numerische Werte direkt, sonst JSON-Payload

## Erweiterung von `registers.yml`

- Pro Modell-ID (String-Key) `points` definieren.
- Jeder Punkt braucht mindestens:
  - `name`
  - `offset`
  - `type` (`u16`, `i16`, `u32_cdab`, `i32_cdab`, `f32_cdab`)
- Optional:
  - `unit`

Beispiel:

```yaml
models:
  "103":
    points:
      - name: pac
        offset: 10
        type: u32_cdab
        unit: W
```

## Tests vor Merge

Mindestens ausführen:

1. `docker compose config`
2. `docker compose up -d --build`
3. `docker compose ps` (alle Services healthy)
4. Influx Smoke-Test (COUNT Query)
5. MQTT Smoke-Test (`mosquitto_sub -v`)
6. `docker compose logs --tail=100 kostal-bridge` auf Fehler prüfen

## Observability & Debug

- Healthcheck der Bridge basiert auf `/tmp/bridge_heartbeat`.
- Bei Verbindungsproblemen prüfen:
  - DNS/Erreichbarkeit von `MODBUS_HOST`
  - Fallback auf `MODBUS_HOST_FALLBACK`
  - Port/Unit-ID (`1502` / `71`)

## Nicht-Ziele (aktuell)

- Kein Schreibkanal zurück zum WR.
- Kein Produktions-Hardening in diesem Repo-Default (TLS/Auth/Secrets/Netzsegmentierung).
- Kein garantierter semantischer Feldkatalog ohne projektspezifisches Mapping.
