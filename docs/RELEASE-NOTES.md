# Release-Notizen

## v0.3.17
- PWA-Installierbarkeit: Manifest (Root/Scope `/`), Icons (192/512 + maskable), Theme-/Apple-Meta in allen Seitenköpfen.
- Service Worker minimal (pass-through, skipWaiting/clients.claim, kein Offline-Cache) mit no-cache-Header; Manifest liefert `application/manifest+json`.
- Öffentliche Auslieferung: FastAPI-Routen `/manifest.webmanifest` und `/service-worker.js`, Icons unter `/static/pwa/`, sichere Registrierung via `pwa.js` nur auf HTTPS/localhost.
- Tests & Tools: HTTP-PWA-Checks, Playwright-PWA-Smokes (Manifest/SW ready), neues `tools/pwa-test.sh --local|--docker` für lokale und Compose-Läufe.
- Nutzung: In Chromium/Edge „Installieren“ sollte nun angeboten werden; Start erfolgt als Standalone-Fenster mit unserem Farbthema. Manifest/Icons/SW sind öffentlich abrufbar (kein AppSecret nötig), API-Schutz bleibt unverändert. Bei Subpfad-Deployment `start_url`/`scope` im Manifest und SW-Registrierungs-URL anpassen.
- Schnelle Verifikation: `./tools/pwa-test.sh --local` (venv + Smoke+PWA) bzw. `./tools/pwa-test.sh --docker --skip-install` (Compose, Port via `PWA_TEST_PORT`/`APP_HTTP_PORT` anpassbar). Einzelne HTTP-Checks: `pytest tests/test_pwa_assets.py`.

## v0.3.16
- UX: Move/Copy-Explorer vergrößert und stabilisiert (mehr Ebenen gleichzeitig aufklappbar ohne Layout-Sprünge, Zielpfad immer sichtbar, kompakter Header).
- Tree-UI modernisiert: klare Einrückung, Hover/Selection-States, feste Steuerungsbreiten; Dialog-Felder (Admin/Rename) passen sich an ohne Überstand.
- Verhalten/Copy/Move-Logik unverändert; Tastaturkürzel (Enter/ESC) im Dialog aktiv.
- Intern: ungenutzte Indexer-Hilfsfunktion `process_file` entfernt, verbleibt nur der Threadpool-Pfad.

## v0.3.15
- Header: ZEN/Theme/Burger stilistisch vereinheitlicht; Burger nur als Punkte, Theme-Dropdown bündig; Admin/Feedback im Menü mit funktionierendem Trigger.
- Navigation: Buttons „Zur Suche“ auf Dashboard/Metrics als Links mit Theme-Style; Extra-Buttons entfernt.
- Zen/Theme: Doppelter Theme-Button entfernt, versteckte Trigger bereinigt.
- Tests: API-/Source-Filter-Tests weiterhin grün.

## v0.3.14
- Zen-Modus für die Trefferliste: Toggle im Header, sichtbare Treffer stufenweise 6/12/alle, ruhigeres Layout mit größeren Fonts/Spacing.
- Normalmodus bleibt kompakt; Snippet-/Spalten-Layout stabilisiert (kein Überlaufen/Überdecken, Auszug bleibt in seiner Spalte).
- Load-More-Button integriert in Zen-Stufen, Reset auf 6 bei neuer Suche; Styling theme-konform aktualisiert.
- Tests: API-/UI-Basis-Tests laufen unverändert.

## v0.3.11
- Explorer: Admin-Operation „Umbenennen…“ (POST `/api/files/{doc_id}/rename`) mit Write-Checks, Temp-Kopie+atomarem Move, Backup in `.quarantine/<Datum>/.rename_backup`, Rollback-Pfad und Audit-Log (`file_ops.jsonl`), Index-Update behält doc_id bei.
- UI: Kontextmenü-Eintrag „Umbenennen…“ nur im Admin-Modus, Modal mit Validierung (kein Pfad/keine Endungsänderung), Treffer aktualisiert ohne Reload.
- Tests ergänzt (Erfolg, 403 ohne Admin, ungültiger Name/Endung, Konflikt, Rollback bei Copy-Fehler); Version erhöht.

## v0.3.10
- Neue Quarantäne-Doku (`docs/QUARANTAENE.md`) mit End-to-End-Flow (Registry, Restore, Hard-Delete, Cleanup, ENV/Locks/Safety).
- Version angehoben.

## v0.3.9
- Quarantäne-Retention: Cleanup-Thread in der App (ENV `QUARANTINE_RETENTION_DAYS`, optional `QUARANTINE_CLEANUP_SCHEDULE`/`QUARANTINE_CLEANUP_DRYRUN`), löscht nur unter `.quarantine`, Audit/Locking pro Datei.
- Registry beim Quarantäne-Move (SQLite `quarantine_entries` mit Pflichtfeldern doc_id/Quelle/Original-/Quarantänepfad/Filename/Actor/moved_at/size), Operation bricht ohne Metadaten ab; Status-Updates für Restore/Hard-Delete/Cleanup.
- Neue Quarantäne-APIs (`/api/quarantine/list|{id}/restore|{id}/hard-delete`) mit Admin-Pflicht und Pfad-Guards; Dashboard-Panel mit Filter (Quelle/Alter/Suche), Restore/Hard-Delete mit Confirm, Anzeige Retention/Cleanup.
- Tests ergänzt (Retention löscht alt, Registry geschrieben, Restore/HARD-Delete, Safety: keine Löschungen außerhalb `.quarantine`, Admin-Pflicht).

## v0.3.8
- Explorer/Quarantäne: Admin-Login (Passwort nur via `ADMIN_PASSWORD`), Kontextmenü „Löschen“ verschiebt Dateien nach `<root>/.quarantine/<YYYY-MM-DD>/docid__name`, entfernt sie sofort aus dem Index und schreibt Audit nach `data/audit/file_ops.jsonl`.
- Quarantäne-Readiness pro Quelle mit Write-Test; Admin-Status liefert `file_ops_enabled`, Quarantäne-Quellen und `index_exclude_dirs`.
- Index-Excludes per `INDEX_EXCLUDE_DIRS` (Default `.quarantine`), Verzeichnisse werden beim Traversieren gepruned (z. B. `.git`, `node_modules`), Quarantäne wird nie indiziert.
- UI: Admin-Modal/Logout, Delete-Confirm, Kontextmenü-Eintrag nur bei aktivem Admin und freigegebenem Root.
- Tests ergänzt (Admin-Auth/Delete/Quarantäne, Exclude-Pruning); Version erhöht.

## v0.3.6
- Quellen-Filter neben dem Suchfeld platziert, Optik an andere Filter angepasst (weißer Hintergrund, klare Umrandung, blauer Aktivzustand, gemeinsame Filtergruppe).
- Dokumentation aktualisiert; Version erhöht.

## v0.3.7
- Auto-Index-Zeitplaner im Dashboard: Toggle, Modus-Buttons (täglich/wöchentlich/intervall), Wochentags-/Intervall-Buttons, Uhrzeit, „Plan speichern“ und „Jetzt ausführen“, Status/Plan-Details und Polling.
- Hintergrund-Scheduler/Runner mit Config-/Status-Persistenz (Config-DB), Locking gegen parallele Läufe, Endpunkte für Config/Status/Run.
- UI-Verfeinerungen (kompaktere Layouts, Buttons statt Dropdowns) und Tests ergänzt.

## v0.3.5
- Neuer Quellen-Filter in der Index-Suche: lädt dynamisch Labels der konfigurierten Quellen, Mehrfachauswahl (OR), gleiches UI-Pattern wie andere Filter, Persistenz per localStorage.
- Suche akzeptiert `source_labels` (mehrere) und filtert entsprechend; `/api/sources` liefert deduplizierte Labels.
- Frontend/Backend-Tests ergänzt (Playwright + API) für Quellen-Filter.

## v0.3.4
- Feedback-UI wieder funktionsfähig: Overlay/Toolbar/Zähler/Bestätigung verdrahtet, Versand gegen `/api/feedback` inkl. Cookie-Secret-Fallback und Statusmeldungen.
- E2E-Absicherung via Playwright (`tests/test_feedback_ui.py`) mit gemocktem Feedback-Endpunkt; Dev-Dependencies ausgelagert in `requirements-dev.txt`.
- Version angehoben.

## v0.3.3
- Suchmodi (Strikt | Standard | Locker) als UI-Schalter mit Persistenz (localStorage/URL) und serverseitigem Contract (`mode`-Parameter). Prefix-Minimum konfigurierbar (`SEARCH_PREFIX_MINLEN`), Default-Mode via `SEARCH_DEFAULT_MODE`.
- Such-Engine-Modi zentral definiert: Strikt = Whole-Token AND, Standard = Whole/PREFIX ab Mindestlänge AND, Locker = Prefix/Teilwort OR. Wildcard nur mit Filter, leere Eingaben blockiert.
- Root-Auswahl im Dashboard: gewählter Pfad wird validiert (unter `base_data_root`, muss existieren) und ohne Fallback auf `/data` übernommen; Preflight/Indexlauf nutzen dieselbe Quelle. „Data“ setzt `/data` nur bei expliziter Wahl.
- Tests ergänzt für Suchmodi, Root-Validierung und Indexlauf mit Config-DB-Roots; Version erhöht.

## v0.3.2
- Konfiguration auf ENV/Docker umgestellt, `.env.example` hinzugefügt; zentrale INI entfernt.
- Mail-Report optional über Dashboard-Toggle (nur bei gesetztem SMTP).
- Live-Log fokussiert auf Warnungen/Fehler mit Pfad; Rotationslog + Ringpuffer, Fortschritt-Logs entfernt.
- Doppelte Bestätigungen für gefährliche Aktionen (Index leeren/neu, Quellen löschen/deaktivieren).
- UI: Qualität-Panel entfernt, Log breit; diverse Sicherheits-/Layout-Anpassungen.
- Tests angepasst, Version erhöht.

## Historie (Auswahl)
- v031: Diagnose (sqlite3 im Image), Heartbeat, Indexer-Log im Dashboard.
- v030: Paginierte Suche & Limits (Top-N, has_more, Debounce).
- v029: Snippet-Highlight & Preview-Kontext.
- v020–v028: UI/Sticky-Header/Version-Badge, Previews, Layout-Fixes.
- v014–v018: Stabilerer Indexer, Status/Fehler-API, Preflight, Aktionen.
- v011–v013: Dashboard & Config-DB, Typen-Auswahl, Fehler-Paging.
- v001–v010: Erste Releases (Indexer, Suche, UI-Grundgerüst, Filter).
- Stop-Button aktiviert (setzt Stop-Flag), Reset/Lauf bleiben getrennt; Preflight-Resultat im Dashboard.
- Single-Writer-Queue bleibt bestehen; letzte Indizierung: 474/474 PDFs erfolgreich, Suche liefert Treffer.

## v019 - Stop-API fix
- Stop-Endpoint aktiviert (Import), Tests: Indexlauf 474/474, Suche liefert Ergebnisse.
## v0.3.12
- CSS: Styles modularisiert (Tokens, Base/Layout, Components, Pages) mit zentralem Einstieg `static/css/app.css`, Vorbereitung für Theming (Design Tokens, Variablen für Farben/Spacing/Radien/Shadows).
- Dashboard/Metrics/Viewer: Inline-Styles und Einzel-CSS in Seitenmodule überführt, Komponenten auf gemeinsame Tokens umgestellt.
- Tests: UI-Zoom-Test robust gegen APP_SECRET aus .env; keine funktionalen Änderungen erwartet.
