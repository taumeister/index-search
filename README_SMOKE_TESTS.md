# E2E/Smoke Tests

## Voraussetzungen
- Python 3.11+
- Abhängigkeiten installieren: `pip install -r requirements-dev.txt`
- Playwright-Browser werden beim ersten Lauf automatisch installiert (abschaltbar mit `--skip-install`).

## One-Command Runs
- Smoke: `python scripts/run_e2e.py --suite smoke`
- Critical (enthält Smoke): `python scripts/run_e2e.py --suite critical`

Optionale Flags:
- `--base-url https://…` für extern/TLS
- `--external` um keinen lokalen Server zu starten (setzt erreichbaren `--base-url` voraus)
- `--port 8010` um lokalen Port zu ändern
- `--app-secret …`, `--admin-password …` zum Überschreiben der Defaults (test-secret/admin)
- `--skip-install` wenn Playwright-Browser schon installiert sind
- `HEADFUL=1` um sichtbar zu testen

## Was der Runner tut
- Legt eine isolierte Laufzeit unter `tmp/e2e-runtime/` an und kopiert Testdaten aus `testdata/sources/demo/`.
- Setzt ENV für Test-Modus (`APP_ENV=test`, `AUTO_INDEX_DISABLE=1`, eigene DB-Pfade).
- Baut den Index einmal vor dem Start.
- Startet uvicorn auf `http://localhost:<port>` und wartet auf `/` + `#search-input`.
- Führt `pytest` mit Marker-Filter aus (`e2e and smoke` bzw. `e2e and (smoke or critical)`).

## Artefakte bei Fehlern
- Unter `test-artifacts/<timestamp>/<testname>/` liegen `trace.zip` und `failure.png`.
- Uvicorn-Log: `tmp/e2e-runtime/logs/uvicorn.log`.

## Sicherheit & Daten
- Quellen/Roots nur aus `tmp/e2e-runtime/data/sources/demo`.
- Auto-Index ist im Testlauf deaktiviert.
- Externe Läufe (`--external`) fassen lokale Testdaten nicht an; Tests mit Root-Manipulation werden dann übersprungen.
