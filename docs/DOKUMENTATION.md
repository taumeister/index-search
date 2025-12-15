# Dokumentation – Index-Suche

## Überblick
- Backend: FastAPI mit SQLite/FTS5 unter `data/index.db`.
- Indexer: Python-Service, durchsucht konfigurierten Wurzelpfade, extrahiert Text (PDF, RTF, MSG, TXT) und schreibt Metadaten + Volltext in die Datenbank.
- Frontend: Explorer-ähnliche Oberfläche (Suchfeld, Tabelle, Preview rechts/Popup), PDF via pdf.js, andere Formate als Text/HTML.
- Konfiguration: zentrale Datei `config/central_config.ini`, wird beim Start validiert.
- Auth: Alle API-Endpunkte (Suche, Dokument, Admin) verlangen `APP_SECRET`, das aus `.env` gelesen oder beim ersten Start erzeugt wird.
- Feedback: Aktivierbar über `FEEDBACK_ENABLED`/`FEEDBACK_TO` und SMTP-Settings; im UI öffnet der Feedback-Button ein Overlay mit WYSIWYG-Light-Toolbar (Fett/Kursiv/Listen), 5000-Zeichen-Limit, Bestätigung und Versand via `/api/feedback`.

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
- `GET /api/search`: Parameter `q`, optional `source_labels` (mehrfach) bzw. `source`, `extension`, `limit`, `offset`; liefert Treffer mit Snippet.
- Suchmodi: Strikt (AND, Whole-Token, keine Prefix/Fuzzy, leere Suche blockt), Standard (AND, Whole-Word oder Prefix ab `SEARCH_PREFIX_MINLEN`, Default), Locker (OR, Prefix/Teilwort tolerant). `SEARCH_DEFAULT_MODE` und `SEARCH_PREFIX_MINLEN` per ENV.
- Requests senden `mode=strict|standard|loose`; Wildcard `*` nur mit aktivem Filter.
- Suchlogik: leere Suche blockiert; Snippets werden serverseitig erzeugt, Matches folgen dem gewählten Modus.
- `GET /api/document/{id}`: Metadaten + Volltext.
- `GET /api/document/{id}/file`: Originaldatei (Download/Inline).
- `GET /api/sources`: Deduplizierte aktive Quellen-Labels (Basis für Quellen-Filter im UI).
- `GET /api/admin/status`: Gesamtanzahl, letzter Lauf, Historie.
- `GET/POST/DELETE /api/admin/roots`: Roots verwalten (aktiv, Pfad, Label). Add-Root validiert: Pfad muss existieren, unter `base_data_root` liegen, kein Fallback auf `/data`.
- `POST /api/admin/index/run`: Indexlauf starten, optional Reset.
- `GET /api/admin/errors`: Fehlerliste.
- `GET /api/admin/tree`: Verzeichnisbaum unter `base_data_root`.
- Auto-Index: `GET/POST /api/auto-index/config` (Plan laden/speichern + Status), `POST /api/auto-index/run` (manuell starten), `GET /api/auto-index/status` (Status/Polling). Scheduler läuft als Hintergrund-Thread, Lock verhindert parallele Läufe.

## Frontend
- Layout: oben kompakter Header (Titel, Zoom-Controls, Dashboard) auf allen Seiten, darunter Suche + Filter; Trefferliste links, Preview rechts (umschaltbar auf Popup).
- Header und Tabellenkopf bleiben beim Scrollen sichtbar; Trefferliste scrollt unabhängig in einem eigenen Scroll-Bereich.
- Header zeigt die aktuelle Versionsnummer (aus `VERSION`) neben dem Titel.
- Filter: Dateityp, Zeitraum (Chips + More-Menü), Quellen-Filter (dynamisch aus aktiven Labels, Mehrfachauswahl, Persistenz per localStorage); alle Filter sitzen rechts neben dem Suchfeld, gruppiert mit weißem Hintergrund/Umrandung, aktiver Zustand blau.
- Preview-Panel: Breite per Griff verstellbar (Session-Scoped gespeichert), enthält Download-, Druck- und Pop-up-Aktionen; Schließen per Klick außerhalb/Escape.
- Tabelle: Spalten sortierbar (Dateiname, Typ, Größe, Geändert) und per sichtbarem Handle in der Breite anpassbar (Persistenz via Storage), Kontextmenü mit Preview/Pop-up/Download/Druck.
- PDF-Preview via pdf.js Iframe, MSG mit Header/Body, RTF/TXT als Text.
- Download-Link öffnet Originaldatei.
- Pop-up/Viewer: kleinere Fenstergröße (ca. 60%/70% des Bildschirms), Druck-Button, minimierte Toolbar; Print öffnet den Dialog ohne neues Browser-Tab.
- Feedback-Overlay: öffnet bei Klick auf den Header-Button, dimmt Hintergrund, Editor mit Toolbar und Zeichenzähler, Abbruch/Senden-Buttons plus zweistufige Bestätigung; ESC oder Klick außerhalb schließt.
- Dashboard: Auto-Index-Zeitplaner (Toggle, Modus-Buttons täglich/wöchentlich/intervall, Uhrzeit, Wochentags-/Intervall-Buttons, Plan speichern, Jetzt ausführen, Plan-/Status-Anzeige), Index-Live-Status, Roots/Explorer, Live-Log, Fehlerliste.

## Tests
- `pytest` deckt Config-Validierung, DB/FTS-Funktion, Indexlauf und API-Suche ab.
- E2E (Playwright): `tests/test_feedback_ui.py` simuliert den Feedback-Flow (Overlay öffnen, Text/Toolbar, Confirm, Erfolg) mit gemocktem `/api/feedback`; `tests/test_source_filter_ui.py` prüft Quellen-Filter (Chips laden, Request-Parameter). Start mit laufendem Container auf `http://localhost:8010` und optional `APP_BASE_URL` zum Überschreiben. Playwright-Assets via `pip install -r requirements-dev.txt` und `playwright install chromium`.
- Scheduler-Tests: `tests/test_auto_index_scheduler.py` validiert Next-Run-Berechnung, Busy-Handling und Auto-Index-Endpunkte.

## Betrieb
- Start (lokal): `uvicorn app.main:app --reload`.
- Indexlauf (manuell): `python -m app.indexer.index_lauf_service` kann ergänzt werden; aktuell Start über `run_index_lauf(config)` aus Code oder Cron/Timer.
- Container: siehe `Dockerfile`/`docker-compose.yml` (Port 8010 -> 8000). Setze `INDEX_ROOT` auf den Host-Pfad, den du in der Config nutzt (z. B. `/home/tom/projekte/INDEX`); der Pfad wird read-only ins Container-Dateisystem gemountet.
