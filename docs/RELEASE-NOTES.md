# Release-Notizen

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
