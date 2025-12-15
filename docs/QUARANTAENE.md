# Quarantäne – Lösch-/Aufbewahrungs-Flow

## Überblick
- Soft-Delete verschiebt Dateien nach `<source_root>/.quarantine/<YYYY-MM-DD>/<doc_id>__<filename>`.
- Registry `quarantine_entries` (SQLite) hält pro Move alle Pflichtfelder und den Status (`quarantined|restored|hard_deleted|cleanup_deleted`).
- Audit-Log: `data/audit/file_ops.jsonl` schreibt jede Aktion (Move, Restore, Hard-Delete, Cleanup) mit Timestamp/Status/Error.
- Indexer ist auf `.quarantine` per `INDEX_EXCLUDE_DIRS` pruned; Quarantäne-Dateien werden nicht indiziert.

## Registry-Felder
- `doc_id`, `source`, `source_root`
- `original_path`, `original_filename`
- `quarantine_path` (unique), `moved_at` (ISO), `actor`
- optional: `size_bytes`, `hash` (derzeit leer)
- Status + Zeitstempel: `restored_path/restored_at`, `hard_deleted_at`, `cleanup_deleted_at`

## ENV/Docker
- `QUARANTINE_RETENTION_DAYS` (Default 30)
- `QUARANTINE_CLEANUP_SCHEDULE` (`daily` default, `hourly`, `off`)
- `QUARANTINE_CLEANUP_DRYRUN` (`false` default)
- Docker: Variablen werden durchgereicht (siehe docker-compose.yml). Index-Exclude bleibt `.quarantine`.

## Aktionen & Pfad-Sicherheit
- Admin-Pflicht für alle Endpunkte; Client liefert nur IDs, keine freien Pfade.
- Realpath-Checks: Originalpfad muss unter `source_root`, Quarantänepfad unter `<root>/.quarantine`.
- Locking pro betroffener Datei verhindert Race mit Cleanup/Restore/Hard-Delete.

### Move in Quarantäne (Soft-Delete)
1) Admin ruft `POST /api/files/{doc_id}/quarantine-delete` auf.
2) Validierung: Dokument existiert, Quelle bereit, Pfad liegt unter Root, Datei vorhanden.
3) Registry-Eintrag wird vor dem Move geschrieben (Pflichtfeld-Garantie). Bei Fehler: Abbruch.
4) Datei wird per os.replace (oder Copy+Delete bei Cross-Device) nach `.quarantine/<YYYY-MM-DD>/docid__name` verschoben.
5) Index-Eintrag wird entfernt; Audit `action=quarantine_delete`.

### Aufbewahrung / Cleanup
- Hintergrund-Thread (nicht unter Pytest) läuft nach Schedule; arbeitet nur innerhalb `.quarantine`.
- Altersermittlung: `mtime` plus Ordnerdatum `<YYYY-MM-DD>` (Sicherheitscheck), es zählt der größere Wert.
- Löscht Dateien älter als `QUARANTINE_RETENTION_DAYS`; Registry-Status → `cleanup_deleted`.
- Dry-Run: setzt `status=dry_run` im Audit, keine Datei/Registry-Änderung.
- Entfernt leere Quarantäne-Unterordner best effort.

### Restore
1) `POST /api/quarantine/{id}/restore`.
2) Validiert Status `quarantined`, Pfade innerhalb erlaubter Roots.
3) Bei Pfad-Kollision: schreibt zurück als `<name>_restored_<timestamp>`.
4) Move zurück (atomar oder Copy+Delete), Registry-Status → `restored`, Audit `action=restore`.
5) Reindex passiert beim nächsten Indexlauf (der Indexer ignoriert `.quarantine`, aber das Original liegt wieder am Ziel).

### Hard-Delete
1) `POST /api/quarantine/{id}/hard-delete`.
2) Validiert Status `quarantined`, Pfad in `.quarantine`.
3) Löscht Datei, Registry-Status → `hard_deleted`, Audit `action=hard_delete`.

## API-Oberfläche
- `GET /api/quarantine/list`: Filter `source`, `max_age_days`, `q` (Name/Pfad). Liefert Registry-Einträge im Status `quarantined`.
- `POST /api/quarantine/{id}/restore`
- `POST /api/quarantine/{id}/hard-delete`
- Admin-Pflicht für alle.

## UI (Dashboard)
- Tab „Quarantäne“ (volle Breite unter Zeitplan): Tabelle mit Datei, Quelle, Originalpfad, Quarantänepfad, Größe, Zeitpunkt.
- Filter: Quelle, Alter (7/30/90), Textsuche. Buttons: Restore, Endgültig löschen (Doppel-Confirm).
- Retention/Cleanup-Status wird als Pillen angezeigt; Auto-Refresh.

## Troubleshooting
- „Quarantäne nicht verfügbar“: Root nicht schreibbar → Quarantäne-Ready-Liste prüfen (`/api/admin/status`).
- Datei bleibt im Index: Indexlauf muss erneut laufen; Restore legt Original zurück, Indexer nimmt sie beim nächsten Lauf wieder auf.
- Cleanup löscht nicht: Retention prüfen, Schedule `off?`, Dry-Run aktiv? Audit-Log einsehen.
