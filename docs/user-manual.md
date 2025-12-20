# Benutzerhandbuch

## Kurzüberblick
- Index-Suche mit Explorer-Oberfläche: Suchfeld oben, Filter rechts, Trefferliste links, Preview rechts.
- Ergebnisse stammen aus den konfigurierten Quellen (Roots); Filter für Dateityp, Zeitraum und Quelle sind jederzeit kombinierbar.
- Admin-Funktionen (Verschieben/Kopieren/Umbenennen/Löschen) erfordern aktiven Admin-Modus und bereitgeschriebene Quellen.

## Suche & Filter
- Freitext-Suche oben, Snippets werden serverseitig erzeugt; leere Suche ist gesperrt.
- Suchmodi: **Strikt** (Whole Token AND), **Standard** (Whole Word/PREFIX AND, Default), **Locker** (Prefix/Teilwort OR). Umschaltbar über die Modus-Schaltfläche rechts neben dem Suchfeld.
- Dateityp-Filter: Alle, PDF, RTF, MSG, TEXT.
- Zeitraum-Filter: Chips (Alle, Gestern, 7T, 30T) plus „More“-Menü (365T, Jahresfilter).
- Quellen-Filter: Lädt aktive Labels aus `/api/sources`; Mehrfachauswahl möglich, Zustand wird lokal gespeichert.

## Ergebnisse & Vorschau
- Tabelle mit Name, Auszug, Geändert, Größe, Typ, Pfad. Spaltenbreiten per Drag anpassbar, Sortierung über Spaltenkopf (Name, Typ, Größe, Geändert).
- Preview rechts: PDF via pdf.js, MSG mit Header/Body, RTF/TXT als Text. Pop-up mit eigenem Fenster möglich.
- Aktionen in der Preview: Drucken, Pop-up öffnen, Original herunterladen.
- Kontextmenü pro Treffer (Rechtsklick oder Menü-Icon): Preview, Pop-up, Download, Drucken; im Admin-Modus zusätzlich Datei-Operationen.

## Zen-Modus („ZEN“-Toggle)
- Reduziert Layout und zeigt Treffer stufenweise (15 → 30 → 45 → alle). Umschalten über den ZEN-Button im Header.
- „Mehr laden“ folgt dem aktuellen Zen-Schritt; Reset auf die erste Stufe bei neuer Suche.

## Explorer-Funktionen (Admin)
- Admin-Login öffnet das Admin-Overlay (Passwort aus ENV); Admin-Always-On kann per ENV aktiviert werden.
- Kontextmenü im Admin-Modus:
  - **Verschieben/Kopieren**: Ziel über Baum auswählen (nur innerhalb bereitgeschriebener Quellen).
  - **Umbenennen**: Validierung ohne Pfadänderungen/Endungswechsel.
  - **Löschen**: Verschiebt in die Quarantäne (nicht direktes Löschen).
- Admin-Status/Roots im Dashboard sichtbar; Datei-Operationen nur bei bereitgeschriebener Quelle aktiv.

## Quarantäne
- Delete verschiebt nach `<root>/.quarantine/<YYYY-MM-DD>/docid__name` und registriert den Vorgang in der DB.
- Restore stellt Dateien an den Originalpfad zurück (Konflikt → Suffix `_restored_<timestamp>`).
- Hard-Delete entfernt Quarantäne-Datei + Registry-Eintrag, nur im Admin-Modus.
- Retention/Cleanup werden im Backend gesteuert (siehe Admin-Handbuch).

## Tipps & FAQ
- „Über“ im Burger-Menü zeigt Titel/Slogan/Version.
- Theme-Umschalter im Header: Auswahl wird in `localStorage` gespeichert.
- Bei fehlenden Treffern oder fehlerhaften Previews: Quelle/Index-Status im Dashboard prüfen und ggf. neu indizieren.
