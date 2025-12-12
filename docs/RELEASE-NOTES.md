# Release-Notizen

## v014 - Status stabil nach Reset
- Admin-Status/Fehler-Endpunkte initialisieren die DB bei fehlenden Tabellen (kein 500 nach Index-Reset).

## v013 - Stabiler Indexer & Dashboard-Fehler
- Indexer: Single-Writer-Queue (ein DB-Writer), `busy_timeout`, lädt bestehende Metadaten, vermeidet Locks bei mehreren Worker-Threads.
- Reset löscht DB-Dateien wie bisher; Fehlerliste jetzt paginiert im Dashboard.
- Fehler-API liefert Total, Dashboard hat Paging (50er Schritte).

## v012 - Dashboard & Config-DB
- Neue Dashboard-Seite (`/dashboard`) mit Root-Verwaltung, Status, Fehlerliste, Index-Start/Reset.
- Konfiguration liegt nun in `config/config.db` (Settings + Roots), verwaltet über UI/API; `central_config.ini` wird nicht mehr benötigt.
- Basis-Explorer zeigt gemountete Unterordner, Roots können aktiviert/deaktiviert/gelöscht werden; Status auto-refresh alle 5s.

## v011 - Feste Typ-Auswahl
- Typ-Filter zeigt immer alle unterstützten Endungen (.pdf/.rtf/.msg/.txt), unabhängig von aktuellen Treffern.

## v010 - Extension-Filter korrigiert
- Endungsfilter sendet die echte Suffix-Schreibweise (inkl. Punkt), Filter greifen wieder auf .pdf/.msg/.rtf/.txt.

## v009 - MSG-Extraktion repariert
- Namenskonflikt behoben: `.msg`-Dateien werden wieder korrekt extrahiert (kein `'function' object has no attribute Message`).

## v008 - Fixierte Leisten
- Kopfzeile (Suchleiste) bleibt beim Scrollen sichtbar.
- Spaltenkopf der Tabelle bleibt weiterhin fixiert; Scrollen der Treffer bleibt möglich.

## v007 - Preview bündig & transparent
- Preview-Overlay dockt bündig an die Tabellenkante an und verschiebt Spalten nicht mehr.
- Semi-transparenter Hintergrund (leicht durchscheinend), Position passt sich beim Resizen an.
- Schrift minimal verkleinert; Standardbreiten bleiben gesetzt (Name, Auszug, Geändert, Größe, Typ, Pfad).

## v006 - Stabilere Tabelle & Preview-Overlay
- Preview-Panel überlagert die Tabelle jetzt ohne Spaltenbreiten zu verschieben.
- Schrift minimal verkleinert; Standardbreiten bleiben gesetzt (Name, Auszug, Geändert, Größe, Typ, Pfad).
- Datumsformat weiterhin vereinheitlicht (de-DE, 2-stellig) für ruhige Spalten.

## v005 - Tabellenlayout & Datum
- Spalten neu angeordnet (Name, Auszug, Geändert, Größe, Typ, Pfad) mit einheitlichen Standardbreiten und kleineren Schriften.
- Datumsformat vereinheitlicht (de-DE mit Datum+Uhrzeit fester Breite) für stabilere Spaltenbreite.
- Jahresfilter (z. B. 2024/2025) liefern jetzt korrekt die Dokumente des jeweiligen Jahres (Parameterübergabe für Zeitbereiche korrigiert).

## v003 - Druck & Pop-up
- Druck öffnet direkt den Druckdialog über ein eingebettetes Iframe (Preview + Viewer), ohne neues Browserfenster.
- Pop-up/Viewer weiter verkleinert (ca. 45–55% des Bildschirms, kleinere Mindestgrößen), PDF-Toolbar minimiert, weniger Rahmen.
- Viewer enthält jetzt einen Druck-Button; Download/Schließen bleiben erhalten.

## v002 - UI-Feinschliff & Suche
- Preview-Panel rechts ist nun per Griff in der Breite verstellbar (Session-Scoped gespeichert); Print-Aktion ergänzt im Header und Kontextmenü.
- Pop-up-Viewer öffnet kleiner (ca. 72% Breite/78% Höhe) für weniger leeren Rand.
- Spalten-Resize blockiert versehentliche Sortierung; sichtbare Handles bleiben, Sortierung bleibt explizit über Header-Klick.
- Suche kombiniert mehrere Wörter strikt mit AND (Prefix-Suche pro Token), Entfernen von Wörtern erweitert die Treffer wieder.

## v001 - Initiale Version
- Grundgerüst für Index-Suche mit FastAPI und SQLite/FTS5.
- Indexer mit Change-Detection, paralleler Verarbeitung, Fehlerprotokoll.
- Explorer-ähnliche Weboberfläche mit Preview (PDF via pdf.js, MSG strukturiert, RTF/TXT als Text).
- Zentrale Konfiguration mit Validator, Beispiel-INI.
- Container-Setup (Standard-Port 8010, Host-Pfad per INDEX_ROOT read-only gemountet), Tests (Config, DB, Indexer, API), Dokumentation.
## v015 - UX-Verbesserungen Dashboard/Suche
- Buttons wechselseitig zwischen Suche und Dashboard.
- Laufzeiten im Dashboard menschenlesbar (Datum/Uhrzeit, Start–Ende).
- Fehlerliste paginiert bleibt erhalten; Explorer lazy-load mit manuellem Aufklappen, Basis-Root direkt klickbar.

## v016 - Actions & Preflight
- Buttons vereinheitlicht, Reset trennt sich vom Laufstart (leert nur).
- Neue Actions: Index starten, Stop-Placeholder, Preflight-Zählung, Reset ohne Start, Reset & Laufstart.
- Preflight zählt Dateien pro Endung unter aktiven Roots und zeigt Ergebnis im Dashboard.
- Suche: Leere Query liefert wieder Treffer (MATCH wird übersprungen).

## v017 - Such-Fix (ORDER BY)
- Leere/`*`-Suchen nutzen kein bm25 mehr, wenn kein FTS-Join erfolgt (kein `no such column documents_fts` mehr).

## v018 - Stabiler Indexlauf & Stop
- DB-Modus auf DELETE-Journal gesetzt, Writer committet nach jedem Item (keine leeren Ergebnisse mehr).
- Stop-Button aktiviert (setzt Stop-Flag), Reset/Lauf bleiben getrennt; Preflight-Resultat im Dashboard.
- Single-Writer-Queue bleibt bestehen; letzte Indizierung: 474/474 PDFs erfolgreich, Suche liefert Treffer.

## v019 - Stop-API fix
- Stop-Endpoint aktiviert (Import), Tests: Indexlauf 474/474, Suche liefert Ergebnisse.
