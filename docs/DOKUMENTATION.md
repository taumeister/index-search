# Dokumentation – Index-Suche

## Überblick
- Backend: FastAPI mit SQLite/FTS5 unter `data/index.db`.
- Indexer: Python-Service, durchsucht konfigurierten Wurzelpfade, extrahiert Text (PDF, RTF, MSG, TXT) und schreibt Metadaten + Volltext in die Datenbank.
- Frontend: Explorer-ähnliche Oberfläche (Suchfeld, Tabelle, Preview rechts/Popup), PDF via pdf.js, andere Formate als Text/HTML.
- Konfiguration: zentrale Datei `config/central_config.ini`, wird beim Start validiert.

## Verzeichnisstruktur
- `app/config_loader.py`: Laden/Validieren der zentralen Konfiguration.
- `app/db/datenbank.py`: SQLite/FTS5-Setup, CRUD, Status.
- `app/indexer/index_lauf_service.py`: Indexlauf, Worker, Change-Detection.
- `app/indexer/extractors.py`: Extraktion pro Dateityp.
- `app/main.py`: FastAPI-App, Routen für Suche, Dokument, Download, Admin-Status.
- `app/frontend/*`: Templates, Styles, JS.
- `config/central_config.ini`: Beispiel/Default-Konfiguration.
- `tests/`: pytest-Tests für Config, DB, Indexer, API.

## Datenbank
- Tabelle `documents`: Metadaten (Quelle, Pfad, Größe, Zeiten, Besitzer, MSG-Felder, Tags).
- FTS5 `documents_fts`: `doc_id`, `content`, `title_or_subject`.
- Logging: `index_runs` (Laufstatus) und `file_errors`.
- WAL-Mode aktiviert.

## Konfiguration (`config/central_config.ini`)
- `[paths] roots`: Liste von Pfaden oder `pfad:label`. Ohne Label wird der letzte Ordnername als `source` genutzt. Leere Liste erlaubt.
- `[indexer]`: `worker_count` (1–8, Default 2), `run_interval_cron` (optional), `max_file_size_mb` (optional).
- `[smtp]`: Host/Port/TLS/Auth/From/To. Wenn leer, kein Mailversand (Start trotzdem möglich).
- `[ui]`: `default_preview` (`panel`/`popup`), `snippet_length`.
- `[logging]`: Level, Log-Verzeichnis, Rotation (MB).

## Indexer
- Change-Detection: Vergleicht `size_bytes` + `mtime`; nur geänderte/neue Dateien werden extrahiert.
- Unterstützte Endungen: `.pdf`, `.rtf`, `.msg`, `.txt`; andere werden ignoriert.
- Entfernt Einträge für fehlende Dateien am Ende des Laufs.
- Fehlerbehandlung pro Datei, Laufstatus in `index_runs`; `file_errors` enthält Details.
- Worker parallelisiert per ThreadPool; Limit per Config.

## Web-API
- `GET /`: Hauptseite.
- `GET /api/search`: Parameter `q`, optional `source`, `extension`, `limit`, `offset`; liefert Treffer mit Snippet.
- `GET /api/document/{id}`: Metadaten + Volltext.
- `GET /api/document/{id}/file`: Originaldatei (Download/Inline).
- `GET /api/admin/status`: Gesamtanzahl, letzter Lauf, Historie.

## Frontend
- Layout: Suche oben, Trefferliste links, Preview rechts (umschaltbar auf Popup).
- PDF-Preview via pdf.js Iframe, MSG mit Header/Body, RTF/TXT als Text.
- Download-Link öffnet Originaldatei.

## Tests
- `pytest` deckt Config-Validierung, DB/FTS-Funktion, Indexlauf und API-Suche ab.

## Betrieb
- Start (lokal): `uvicorn app.main:app --reload`.
- Indexlauf (manuell): `python -m app.indexer.index_lauf_service` kann ergänzt werden; aktuell Start über `run_index_lauf(config)` aus Code oder Cron/Timer.
- Container: siehe `Dockerfile`/`docker-compose.yml` (unten).
