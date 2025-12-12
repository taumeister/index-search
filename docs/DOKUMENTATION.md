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

## Konfiguration (`config/config.db`)
- SQLite-basierte Konfiguration mit Tabellen `settings` (Basiswerte) und `roots` (Quellen).
- Defaults werden beim Start angelegt (`base_data_root=/data`, `worker_count=2`, `snippet_length=240`, Logging etc.).
- Verwaltung erfolgt über das Dashboard (`/dashboard`): Roots hinzufügen/entfernen/aktivieren, Indexlauf starten, Reset auslösen.

## Indexer
- Change-Detection: Vergleicht `size_bytes` + `mtime`; nur geänderte/neue Dateien werden extrahiert.
- Unterstützte Endungen: `.pdf`, `.rtf`, `.msg`, `.txt`; andere werden ignoriert.
- Entfernt Einträge für fehlende Dateien am Ende des Laufs.
- Fehlerbehandlung pro Datei, Laufstatus in `index_runs`; `file_errors` enthält Details.
- Worker parallelisiert per ThreadPool; Limit per Config.

## Web-API
- `GET /`: Hauptseite.
- `GET /dashboard`: System/Dashboard mit Roots/Status.
- `GET /api/search`: Parameter `q`, optional `source`, `extension`, `limit`, `offset`; liefert Treffer mit Snippet.
- Suchlogik: Mehrere Wörter werden als AND kombiniert, Tokens werden als Prefix (`wort*`) gesucht; leere Suche zeigt alle Treffer.
- `GET /api/document/{id}`: Metadaten + Volltext.
- `GET /api/document/{id}/file`: Originaldatei (Download/Inline).
- `GET /api/admin/status`: Gesamtanzahl, letzter Lauf, Historie.
- `GET/POST/DELETE /api/admin/roots`: Roots verwalten (aktiv, Pfad, Label).
- `POST /api/admin/index/run`: Indexlauf starten, optional Reset.
- `GET /api/admin/errors`: Fehlerliste.
- `GET /api/admin/tree`: Verzeichnisbaum unter `base_data_root`.

## Frontend
- Layout: Suche oben, Trefferliste links, Preview rechts (umschaltbar auf Popup).
- Preview-Panel: Breite per Griff verstellbar (Session-Scoped gespeichert), enthält Download-, Druck- und Pop-up-Aktionen; Schließen per Klick außerhalb/Escape.
- Tabelle: Spalten sortierbar (Dateiname, Typ, Größe, Geändert) und per sichtbarem Handle in der Breite anpassbar (Persistenz via Storage), Kontextmenü mit Preview/Pop-up/Download/Druck.
- PDF-Preview via pdf.js Iframe, MSG mit Header/Body, RTF/TXT als Text.
- Download-Link öffnet Originaldatei.
- Pop-up/Viewer: kleinere Fenstergröße (ca. 60%/70% des Bildschirms), Druck-Button, minimierte Toolbar; Print öffnet den Dialog ohne neues Browser-Tab.

## Tests
- `pytest` deckt Config-Validierung, DB/FTS-Funktion, Indexlauf und API-Suche ab.

## Betrieb
- Start (lokal): `uvicorn app.main:app --reload`.
- Indexlauf (manuell): `python -m app.indexer.index_lauf_service` kann ergänzt werden; aktuell Start über `run_index_lauf(config)` aus Code oder Cron/Timer.
- Container: siehe `Dockerfile`/`docker-compose.yml` (Port 8010 -> 8000). Setze `INDEX_ROOT` auf den Host-Pfad, den du in der Config nutzt (z. B. `/home/tom/projekte/INDEX`); der Pfad wird read-only ins Container-Dateisystem gemountet.
