# Release-Notizen

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
