# Spec: kostal-zu-influx-bridge

Sollzustand der Bridge. Der Code ist die Umsetzung, diese Spec beschreibt Verhalten und Schnittstellen.
Wird eine Schnittstelle geändert, wird die Spec im selben Commit nachgezogen.

| Datei | Inhalt |
|---|---|
| [`architektur.md`](architektur.md) | Komponenten, Abfragezyklus, Fehlerverhalten |
| [`datenmodell.md`](datenmodell.md) | Influx- und MQTT-Schema, Retention, Registermapping |
| [`legacy-sink.md`](legacy-sink.md) | Übergangs-Sink nach `haus.strom` |
| [`betrieb.md`](betrieb.md) | Konfiguration, Tests, Abgrenzung zu `docker-mini` |
| [`mcp.md`](mcp.md) | Read-only MCP-Server für Analysen |

## Grundsätze

- **Read-only:** kein Schreibzugriff auf Wechselrichter-Register.
- **Kein generischer Export:** Publiziert wird nur, was in `config/registers.yml` steht.
- **Stabile Namen:** Feld- und Topic-Namen ändern sich nur mit expliziter Migrationsnotiz.
- **Additive Env-Keys:** Neue Variablen kommen dazu, bestehende werden nicht umbenannt.

**Nicht-Ziele:** Schreibkanal zum Wechselrichter, TLS/Auth/Secrets-Hardening im Repo-Default,
garantierter Feldkatalog ohne `registers.yml`-Mapping.
