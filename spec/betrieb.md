# Betrieb

## Anlage

| Gerät | Daten |
|---|---|
| Wechselrichter | Kostal PLENTICORE plus 8.5, Artikelnummer 10335958, HW 0200 |
| WR-Firmware | UI 01.30.12092, MC 01.80, IOC 01.80, Richtlinie DE VDE4105 cosphi=1 |
| Batterie | BYD Battery-Box Premium HVM: 1× BCU HVS/HVM-BCL, 4× Modul HVM-2.76 (Aufdruck „II“) |

Die Firmware ist relevant für die Wortreihenfolge der `U32`-Register, siehe [`datenmodell.md`](datenmodell.md).

## Konfiguration

Alle Parameter kommen aus der Umgebung, Vorlage ist `.env.example`. Im Repo-Stack reicht `kostal-bridge` die `.env`
per `env_file` durch.

## Tests

Unit-Tests liegen in `app/tests/` und laufen im Bridge-Image, ohne Wechselrichter und ohne Influx:

```bash
docker compose build kostal-bridge
docker compose run --rm --no-deps -v "$PWD/app:/app" kostal-bridge python -m unittest discover -s tests
```

Die Tests landen nicht im Image, deshalb der Mount von `app/`. Smoke-Tests für den laufenden Stack stehen in `CLAUDE.md`.

## Deployment

Deployt wird aus dem Repo `docker-mini`, nicht von hier. Es bindet dieses Repo als Submodule
`mini/apps/kostal-bridge` ein und hat eine eigene Compose-Datei `mini/apps/docker-compose.yml`, die Bridge-Variablen
dort einzeln setzt. Neue Variablen müssen deshalb auch dort oder in der `.env` von `docker-mini` ergänzt werden.

| | Repo-Stack | Mini |
|---|---|---|
| Influx-Auth | an | aus |
| Modbus-Host | `.env` | `apps/docker-compose.yml` |
| Retention, Downsampling | `influxdb/init/` | `docker-mini` |
