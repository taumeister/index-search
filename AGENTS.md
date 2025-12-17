# AGENTS.md

## Grundregeln für Kommunikation

- Antworte grundsätzlich **nur mit Text**, **niemals mit Code** (keine Codeblöcke, keine Snippets, keine Diffs).
- Jede Frage muss **immer beantwortet** werden (keine Ausweichantworten).
- Wenn ich (Codex) Rückfragen stelle, müssen diese **nummeriert** sein (1., 2., 3., …), damit du eindeutig referenzieren kannst.

## Ausführungsprinzip

- Aus allen Antworten dürfen sich To-Dos ergeben.
- **Bevor** ich irgendein To-Do ausführe (Dateien ändern, Befehle ausführen, Inhalte erzeugen/anzeigen, Services/Container beeinflussen), muss ich dich **explizit fragen**, ob ich es ausführen soll.
- Ohne deine Freigabe: **keine Ausführung**, **keine Änderungen**, **kein Code anzeigen**.

## Verbindlicher Arbeitszyklus (niemals abweichen)

### Phase A — Antworten & To-Dos vorschlagen
1) Beantworte die gestellte Frage vollständig in Text.
2) Falls To-Dos nötig/sinnvoll sind: liste sie als Text auf.
3) Frage anschließend: **„Soll ich diese To-Dos ausführen?“**

### Phase B — Umsetzung (nur nach Freigabe)
4) Nach Freigabe: setze die freigegebenen To-Dos um.
5) Dabei: arbeite selbstständig, ohne Zwischenabbruch mit „mach du jetzt noch X“.

### Phase C — Testen bis Ziel erreicht ist
6) Nach jeder relevanten Änderung: führe alle notwendigen Tests/Checks aus.
7) Wenn Tests fehlschlagen: behebe die Ursache und teste erneut.
8) **Nicht stoppen**, bevor das gewünschte Verhalten erreicht ist und die Tests erfolgreich sind.
9) Wenn etwas nicht testbar ist oder Voraussetzungen fehlen: schaffe die Voraussetzungen (z. B. Start/Restart von Containern/Services, notwendige Konfiguration/Abhängigkeiten), dann erneut testen.

### Phase D — Ergebnisbericht
10) Wenn Ziel erreicht: liefere eine **kurze Stichpunkt-Zusammenfassung**:
   - Was wurde getan?
   - Was wurde getestet?
   - Was ist jetzt zu erwarten?

### Phase E — Commit & Dokumentation (nur nach Freigabe)
11) Frage anschließend: **„Soll ich jetzt committen und dokumentieren?“**
12) Nur nach Freigabe:
   - Dokumentation aktualisieren
   - Version hochsetzen
   - Release Notes aktualisieren
   - Commit erstellen

## Admin-/API-Debug-Vorgehen (verbindlich)

- Bei Admin-Fehlern immer das `APP_SECRET` und `ADMIN_PASSWORD` aus der lokalen `.env` verwenden und einen gültigen Admin-Login per API durchführen (`/api/admin/login` mit Header `X-App-Secret`), bevor geschützte Endpunkte getestet werden.
- Nach Login Cookies/Token verwenden (kein anonymer Zugriff), dann `/api/admin/status`, `/api/admin/indexer_status` und eine geschützte Datei-Operation (Rename/Move/Delete) aufrufen, um Verhalten zu prüfen.
- Bei Änderungen an Quellen/Roots: aktive Roots aus der DB lesen (`config/config.db`) und sicherstellen, dass entfernte/inaktive Roots nicht mehr in API-Responses (z. B. `/api/sources`, Move-Ziele) auftauchen.
