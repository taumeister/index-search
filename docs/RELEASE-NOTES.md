# Release-Notizen

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
