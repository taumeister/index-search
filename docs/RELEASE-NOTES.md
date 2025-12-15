# Release-Notizen

## v0.3.6
- Quellen-Filter neben dem Suchfeld platziert, Optik an andere Filter angepasst (weißer Hintergrund, klare Umrandung, blauer Aktivzustand, gemeinsame Filtergruppe).
- Dokumentation aktualisiert; Version erhöht.

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
