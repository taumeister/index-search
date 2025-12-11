# Release-Notizen

## v001 - Initiale Version
- Grundgerüst für Index-Suche mit FastAPI und SQLite/FTS5.
- Indexer mit Change-Detection, paralleler Verarbeitung, Fehlerprotokoll.
- Explorer-ähnliche Weboberfläche mit Preview (PDF via pdf.js, MSG strukturiert, RTF/TXT als Text).
- Zentrale Konfiguration mit Validator, Beispiel-INI.
- Container-Setup (Standard-Port 8010, Host-Dateisystem read-only unter /hostfs), Tests (Config, DB, Indexer, API), Dokumentation.
