# Dokumentation – Index-Suche

## Überblick
- Backend: FastAPI mit SQLite/FTS5 unter `data/index.db`.
- Indexer: Python-Service, durchsucht konfigurierten Wurzelpfade, extrahiert Text (PDF, RTF, MSG, TXT) und schreibt Metadaten + Volltext in die Datenbank.
- Frontend: Explorer-ähnliche Oberfläche (Suchfeld, Tabelle, Preview rechts/Popup), PDF via pdf.js, andere Formate als Text/HTML.
- Konfiguration: ENV-Variablen für Basis-Settings (Docker/Compose) plus SQLite-basierte Config-DB `config/config.db` für UI/Roots.
- Auth: Alle API-Endpunkte (Suche, Dokument, Admin) verlangen `APP_SECRET`, das aus `.env` gelesen oder beim ersten Start erzeugt wird.
- Admin-Passwort: Backend liest `ADMIN_PASSWORD` (Default `admin`), Vorgabe per ENV/Compose setzen; Passwort wird nicht im Frontend gespeichert, erneutes Öffnen des Admin-Overlays erfordert Re-Auth.
- Admin-Always-On: Optional per `ADMIN_ALWAYS_ON=true` (Default false). Nur in vertrauenswürdigen Setups nutzen; ersetzt nicht das `APP_SECRET`. Siehe `docs/ADMIN_ALWAYS_ON.md`.
- Feedback: Aktivierbar über `FEEDBACK_ENABLED`/`FEEDBACK_TO` und SMTP-Settings; im UI öffnet der Feedback-Button ein Overlay mit WYSIWYG-Light-Toolbar (Fett/Kursiv/Listen), 5000-Zeichen-Limit, Bestätigung und Versand via `/api/feedback`.
- Lizenz: MIT (siehe `LICENSE`), bereitgestellt „as is“ ohne Gewähr.

## Verzeichnisstruktur
- `app/config_loader.py`: Laden/Validieren der zentralen Konfiguration.
- `app/db/datenbank.py`: SQLite/FTS5-Setup, CRUD, Status.
- `app/indexer/index_lauf_service.py`: Indexlauf, Worker, Change-Detection.
- `app/indexer/extractors.py`: Extraktion pro Dateityp.
- `app/main.py`: FastAPI-App, Routen für Suche, Dokument, Download, Admin-Status.
- `app/frontend/*`: Templates, Styles, JS.
- `config/config.db`: persistierte Settings/Roots aus dem Dashboard; `config/metrics_thresholds.json` (optional) für Schwellwerte.
- `tests/`: pytest-Tests für Config, DB, Indexer, API.

## Datenbank
- Tabelle `documents`: Metadaten (Quelle, Pfad, Größe, Zeiten, Besitzer, MSG-Felder, Tags).
- FTS5 `documents_fts`: `doc_id`, `content`, `title_or_subject`.
- Logging: `index_runs` (Laufstatus) und `file_errors`.
- Lauf-Events: `index_run_events` protokolliert pro Lauf alle Pfad-Aktionen (`added|updated|removed`) mit Zeitstempel, Quelle, Actor (indexer) und optionaler Message; abrufbar über Admin-API/Report.
- Fehler-Handling: `file_errors.ignored` markiert erwartbare PDF-Fehler (z. B. verschlüsselt/kaputte Streams). Ignorierte Fehler zählen nicht mehr in den Error-Kacheln/Mails, bleiben aber in der Detail-Ansicht markiert.
- Quarantäne-Registry: `quarantine_entries` speichert pro Move `doc_id`, Quelle, Original-/Quarantänepfad, Filename, Actor, Größe, Zeitstempel, Status (`quarantined|restored|hard_deleted|cleanup_deleted`), optionale Restore-/Delete-Zeitpunkte.
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
- Ausschlüsse: `INDEX_EXCLUDE_DIRS` (kommagetrennt, Default `.quarantine`) schließt Ordner/Pfade pro Quelle beim Traversieren aus (z. B. `.git`, `node_modules`, `.quarantine`), damit sie gar nicht indiziert werden.

## Quarantäne & Cleanup
- ENV: `QUARANTINE_RETENTION_DAYS` (Default 30), `QUARANTINE_CLEANUP_SCHEDULE` (Default `daily`, `hourly` oder `off`), `QUARANTINE_CLEANUP_DRYRUN` (optional Dry-Run).
- Cleanup-Thread läuft im App-Prozess (nicht unter Pytest), löscht ausschließlich unter `<root>/.quarantine/` anhand `mtime`/Datumsordner und schreibt Audit nach `data/audit/file_ops.jsonl`; Locking schützt vor parallelem Restore/Move.
- Registry-Status wird nach Cleanup auf `cleanup_deleted`, nach Hard-Delete auf `hard_deleted`, nach Restore auf `restored` gesetzt. Sidecar-Dateien werden nicht genutzt, alles landet in `quarantine_entries`.

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
- `GET /api/admin/status`: Gesamtanzahl, letzter Lauf, Historie, Admin-/File-Op-Status, `index_exclude_dirs`.
- Index-Läufe (Details): `GET /api/admin/index/run/{id}/summary` (Counts + Fehler), `GET /api/admin/index/run/{id}/events` (Pfad-Events, filterbar per `action=added|updated|removed`), `GET /api/admin/index/run/{id}/errors` (Fehlereinträge inkl. ignored-Flag).
- Admin/Explorer/Quarantäne: `POST /api/admin/login`/`logout` (Passwort via `ADMIN_PASSWORD`, Session-Cookie), `/api/admin/status` liefert `file_ops_enabled`, Quarantäne-Ready-Liste und Cleanup-Konfig; `POST /api/files/{doc_id}/quarantine-delete` verschiebt Treffer in `<root>/.quarantine/<YYYY-MM-DD>/docid__name`, schreibt Metadaten in `quarantine_entries` und entfernt ihn aus dem Index; `GET /api/quarantine/list` listet Registry-Einträge (Filter Quelle/Alter/Text), `POST /api/quarantine/{id}/restore` stellt Dateien wieder her (bei Konflikt Suffix `_restored_<timestamp>`), `POST /api/quarantine/{id}/hard-delete` entfernt Quarantäne-Datei + Registry-Eintrag. Alle File-Ops: Admin-Pflicht, Pfad-Guard (realpath innerhalb Quelle/.quarantine), Locking pro Datei.
- `GET/POST/DELETE /api/admin/roots`: Roots verwalten (aktiv, Pfad, Label). Add-Root validiert: Pfad muss existieren, unter `base_data_root` liegen, kein Fallback auf `/data`.
- `POST /api/admin/index/run`: Indexlauf starten, optional Reset.
- `GET /api/admin/errors`: Fehlerliste.
- `GET /api/admin/tree`: Verzeichnisbaum unter `base_data_root`.
- Auto-Index: `GET/POST /api/auto-index/config` (Plan laden/speichern + Status), `POST /api/auto-index/run` (manuell starten), `GET /api/auto-index/status` (Status/Polling). Scheduler läuft als Hintergrund-Thread, Lock verhindert parallele Läufe.

## Frontend
### Styles / Theming
- Einstieg: `app/frontend/static/css/app.css` wird in den Templates geladen (statt monolithisch `styles.css`).
- Struktur: `00-tokens.css` (Design Tokens), `01-base.css` (Body/Typo), `02-layout.css` (Header/Main), Komponenten unter `03-components/*` (Buttons, Filter/Form, Tabellen, Preview, Dialoge, Context-Menu, Toasts, Feedback), Seiten unter `04-pages/*` (Search, Dashboard, Metrics/Matrix, Viewer).
- Tokens: Farben, Abstände, Radien, Schatten, Focus-Ring, Filter-Defaults; Legacy-Aliase (`--border`, `--muted`, `--panel` etc.) für Kompatibilität bestehen.
- Viewer/Dashboard/Metrics nutzen jetzt ihre Seiten-CSS statt Inline/Separate Files; `static/styles.css` und `static/viewer.css` leiten nur noch auf `css/app.css`.

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
- Dashboard: Auto-Index-Zeitplaner (Toggle, Modus-Buttons täglich/wöchentlich/intervall, Uhrzeit, Wochentags-/Intervall-Buttons, Plan speichern, Jetzt ausführen, Plan-/Status-Anzeige), Index-Live-Status, Roots/Explorer, Live-Log, Fehlerliste, Quarantäne-Panel (Liste der Registry-Einträge mit Filter Quelle/Alter/Suche, Aktionen Restore/Hard-Delete mit Bestätigung, Anzeige Retention/Cleanup-Konfig, Auto-Refresh). Lauf-Details: „Details“-Button und klickbare Kacheln öffnen ein Modal mit Tabs für Added/Updated/Removed/Errors; Fehler zeigen Ignored-Badge für erwartbare PDF-Probleme; Daten aus `index_run_events`/`file_errors`.

### Kontextmenü erweitern
- Zentrale Definition in `app/frontend/static/main.js`: Gruppen stehen in `CONTEXT_MENU_SECTIONS`, Einträge in `CONTEXT_MENU_ITEMS`.
- Pro Eintrag: id/label, group (`view|export|manage|more`), order, icon (z. B. eye, window, download, print, copy, edit, trash, feedback, shield, filter), optional shortcut oder Caption/Hinweis, `danger` für destruktive Optik.
- Sichtbarkeit/Status: `visibleIf` und `enabledIf` bekommen den Kontext mit doc_id, Name, Pfad, Quelle, Extension und Flag `canManageFile`; Rückgabe false blendet aus bzw. deaktiviert.
- Handler: bekommt denselben Kontext, führt die Aktion aus (Preview/Download/Popup etc.); Menü schließt nach Auswahl automatisch, falls `closeOnSelect` nicht auf false gesetzt wird.
- Neue Gruppen: Überschrift in `CONTEXT_MENU_SECTIONS` ergänzen, Einträge mit passendem group hinzufügen; Reihenfolge über `order`.
- Platzhalter/Future-Items können über `FUTURE_CONTEXT_MENU_FLAGS` oder `visibleIf`-/`enabledIf`-Bedingungen vorbereitet werden, ohne das UI zu stören.
- Verschieben/Kopieren: Kontextmenü-Einträge „Verschieben…“/„Kopieren…“ öffnen ein Overlay mit lazy geladenem Tree aller bereitgestellten Quellen (Multi-Source). Endpunkte: `GET /api/files/tree` (ohne `source` → Quellen-Roots, mit `source`/`path` → Child-Verzeichnisse), `POST /api/files/{doc_id}/move` und `POST /api/files/{doc_id}/copy` (Payload `target_source`, `target_dir`). Beide prüfen Pfad-Guards/Locks, aktualisieren Index (Move: Quelle/Path anpassen; Copy: neues Dokument mit Inhalt/Metadaten).

## Tests
- `pytest` deckt Config-Validierung, DB/FTS-Funktion, Indexlauf und API-Suche ab.
- E2E (Playwright): `tests/test_feedback_ui.py` simuliert den Feedback-Flow (Overlay öffnen, Text/Toolbar, Confirm, Erfolg) mit gemocktem `/api/feedback`; `tests/test_source_filter_ui.py` prüft Quellen-Filter (Chips laden, Request-Parameter). Start mit laufendem Container auf `http://localhost:8010` und optional `APP_BASE_URL` zum Überschreiben. Playwright-Assets via `pip install -r requirements-dev.txt` und `playwright install chromium`.
- Scheduler-Tests: `tests/test_auto_index_scheduler.py` validiert Next-Run-Berechnung, Busy-Handling und Auto-Index-Endpunkte.
- DB-Reports: `scripts/db_report.sh` liefert Lauf-Statistik, Events/Errors/Missing; siehe `docs/db_checks.txt`.

## Betrieb
- Start (lokal): `uvicorn app.main:app --reload`.
- Indexlauf (manuell): `python -m app.indexer.index_lauf_service` kann ergänzt werden; aktuell Start über `run_index_lauf(config)` aus Code oder Cron/Timer.
- Container: siehe `Dockerfile`/`docker-compose.yml` (Port 8010 -> 8000). Setze `INDEX_ROOT` auf den Host-Pfad, den du in der Config nutzt (z. B. `/home/tom/projekte/INDEX`); der Pfad wird read-only ins Container-Dateisystem gemountet.
