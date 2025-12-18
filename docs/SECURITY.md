# Sicherheitsleitfaden: Netzlaufwerke, Indexer & Quarantäne

## Warum das wichtig ist (Kurz erklärt)
Viele Daten liegen auf SMB/Netzlaufwerken, die gelegentlich ausfallen oder getrennt werden können. Wenn das passiert, dürfen wir auf keinen Fall:
- Dateien löschen oder „prunen“, nur weil das Laufwerk gerade leer oder weg ist.
- Quarantäne-Aktionen durchführen, wenn nicht geschrieben werden kann.
- Irgendwo außerhalb der erlaubten Ordner löschen oder verschieben.

Deshalb gibt es nun zentrale Readiness-Prüfungen und Path-Guards, die Abläufe abbrechen, statt „halb“ zu laufen oder Daten zu verlieren. Das Dashboard zeigt klar, wenn ein Laufwerk nicht bereit ist.

## Technische Absicherung
### Readiness-Gates
- **Quellen-Check vor jedem Indexlauf (manuell + Auto)**: listdir/stat auf jedem Root; leeres Mount plus vorhandene Dokumente ⇒ nicht bereit. Ergebnis: Lauf startet nicht, Status 503/„Netzlaufwerk nicht bereit“, kein Prune.
- **Post-Check vor Prune**: Wenn nach dem Scan ein Root nicht bereit ist, wird `remove_documents_not_scanned` übersprungen → keine Löschungen.
- **Auto-Index-Scheduler**: Prüft vor Start; liefert `not_ready`, Lauf wird nicht gestartet.

### Quarantäne-Gate
- **Schreibtest** im Quarantäne-Ordner (Temp-Datei mit fsync).
- Alle Quarantäne-APIs (list/restore/hard-delete/delete) brechen mit 503/Fehlermeldung ab, wenn Source oder Quarantäne nicht bereit ist.
- Dashboard zeigt „Quarantäne nicht bereit“ mit Issue-Details.

### Auto-Purge/Retention
- Standard: **Auto-Purge aus** (Cleanup-Schedule „off“), nur manuell auslösbar, wenn explizit aktiviert.
- Cleanup läuft ausschließlich innerhalb `.quarantine` und durchläuft Path-Guard.

### Path-Safety Guard
- Zentraler `safe_delete`/Guard mit realpath+Allowlist, Symlink- und „..“-Schutz, Fail-closed.
- Cleanup und Hard-Delete nutzen den Guard; Löschversuche außerhalb Quarantäne oder via Symlink werden blockiert.
- Indexer arbeitet nur read-only auf Quellen; Schreiben in Source-Pfade findet nicht statt.

### Nutzerfeedback / UI
- Dashboard-Buttons zeigen verständliche Fehlermeldungen („Netzlaufwerk nicht bereit“) bei Startversuchen.
- Quarantäne-Status-Pill zeigt Issues und dass Auto-Purge aus ist.

## Relevante Stellen im Code
- **Readiness**: `app/services/readiness.py`
- **Indexer-Gate/Prune-Block**: `app/indexer/index_lauf_service.py`, `app/index_runner.py`
- **Auto-Index-Gate**: `app/auto_index_scheduler.py`, `app/main.py` (Endpoints)
- **Quarantäne-Gate & Path-Guard**: `app/services/file_ops.py`, Status-Ausgabe `app/main.py`
- **UI-Hinweise**: `app/frontend/templates/dashboard.html`
- **Config/Defaults (Auto-Purge aus)**: `app/config_loader.py`

## Tests (Beispiele)
- Quellen offline ⇒ Index-Start 503, keine Prune-Löschungen.
- Offline/Empty-Mount während Lauf ⇒ keine Removals.
- Quarantäne nicht schreibbar ⇒ Quarantäne-APIs 503, keine Seiteneffekte.
- Path-Guard blockt Delete außerhalb Quarantäne inkl. Symlink/„..“.
- Kommandos lokal (venv): `pytest tests/test_readiness_guards.py tests/test_file_ops.py`
- Docker: `docker compose run --rm web pytest tests/test_readiness_guards.py tests/test_file_ops.py`
