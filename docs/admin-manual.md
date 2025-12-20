# Admin-Handbuch

## Start & Betrieb
- **Docker Compose**: `docker compose up -d` startet den Web-Service (`APP_HTTP_PORT` → Port 8000 im Container, Default Host-Port 8010). Stoppen mit `docker compose down`.
- **Reverse Proxy**: Beispiel unter `nginx/index-suche.conf` (TLS, Proxy auf `127.0.0.1:8010`, Header `X-Internal-Auth`).
- **User/Permissions**: Container läuft als `appuser`, Daten werden aus dem Host-Pfad per Bind-Mount unter `/data` eingebunden.
- **Datenpfade**: Index-DB unter `data/index.db`, Config-DB unter `config/config.db`, Audit/Logs unter `data/audit` und `logs/`.

## Admin-Zugang
- API-Schutz über `APP_SECRET` (Header `X-App-Secret`), Admin-Login via `/api/admin/login` mit `ADMIN_PASSWORD` (Session-Cookie `admin_session`).
- `ADMIN_ALWAYS_ON=true` erlaubt Admin-Operationen ohne Login (nur in vertrauenswürdigen Umgebungen nutzen).
- Admin-Status über `/api/admin/status`; Admin-/Quellen-Ready-Informationen erscheinen auch im Dashboard.

## Wichtige ENV-/Compose-Variablen
| Variable | Default | Beschreibung |
| --- | --- | --- |
| `APP_SECRET` | generiert oder aus `.env` | Muss jedem API-Call als `X-App-Secret` mitgegeben werden. |
| `ADMIN_PASSWORD` | `admin` | Passwort für `/api/admin/login`. |
| `ADMIN_ALWAYS_ON` | `false` | Admin-Modus ohne Login aktivieren (nur trusted). |
| `DATA_HOST_PATH` | `/home/tom/projekte/99_index` (Beispiel) | Host-Pfad für Daten, wird nach `/data` gemountet. |
| `DATA_CONTAINER_PATH` | `/data` | Basis-Pfad für Quellen im Container. |
| `INDEX_ROOTS` | leer | Optionale Root-Vorgabe (`/data/path:label`), meist via UI/DB gesetzt. |
| `INDEX_WORKER_COUNT` | `2` | Parallelität des Indexers. |
| `INDEX_MAX_FILE_SIZE_MB` | `0` | 0 = kein Limit, sonst Maximalgröße. |
| `INDEX_EXCLUDE_DIRS` | `.quarantine` | Kommagetrennte Ordner, die beim Scannen ausgeschlossen werden. |
| `QUARANTINE_RETENTION_DAYS` | `30` | Aufbewahrungstage für Quarantäne-Dateien. |
| `QUARANTINE_CLEANUP_SCHEDULE` | `daily` | `daily`, `hourly` oder `off`. |
| `QUARANTINE_CLEANUP_DRYRUN` | `false` | Nur prüfen, nicht löschen. |
| `LOG_LEVEL` | `INFO` | Logging-Level. |
| `LOG_DIR` | `logs` | Pfad für Lauf-Logs. |
| `LOG_ROTATION_MB` | `30` | Größe für Log-Rotation. |
| `SMTP_*`, `SEND_REPORT_ENABLED` | siehe `.env.example` | SMTP/Reporting, optional für E-Mail-Report. |
| `FEEDBACK_ENABLED`, `FEEDBACK_TO` | `true`, Mail | Aktiviert Feedback-Overlay und Zieladresse. |
| `APP_TITLE`, `APP_SLOGAN` | leer | Branding für Header und Über-Overlay. |

## Quellen & Indexierung
- Aktive Quellen werden in `config/config.db` gepflegt (Dashboard). Pfade müssen unter `DATA_CONTAINER_PATH` liegen.
- Indexlauf über Dashboard (Start/Stop/Reset) oder Auto-Index-Scheduler. Scheduler prüft Readiness vor Start.
- Re-Index/Reset führen keine Löschung durch, wenn ein Root nicht bereit ist (Readiness-Gate).
- `INDEX_EXCLUDE_DIRS` schützt z. B. `.quarantine` vor Indizierung.

## Quarantäne & File-Ops
- Delete verschiebt nach `<root>/.quarantine/<YYYY-MM-DD>/docid__name` und schreibt Audit nach `data/audit/file_ops.jsonl`.
- Restore/Hart-Löschen nur mit aktivem Admin. Path-Guard verhindert Aktionen außerhalb des Root/Quarantäne.
- Cleanup-Thread löscht alte Quarantäne-Dateien gemäß Retention/Schedule; Dry-Run möglich.

## Backup & Restore
- Sichern: `data/index.db`, `config/config.db`, `data/audit`, `logs/`, optional `.env`.
- Wiederherstellung: Container stoppen, Dateien zurückspielen, danach App starten; Index-Lauf bei Bedarf erneut auslösen.
- Quellen-Mounts sind read-only für den Indexer; Quarantäne benötigt Schreibrechte in `<root>/.quarantine/`.

## Troubleshooting
- Status prüfen: `/api/admin/status`, `/api/admin/indexer_status`, `/api/admin/errors`.
- Logs: `logs/` (Uvicorn/Indexer), Quarantäne-Audit unter `data/audit/file_ops.jsonl`.
- Netzwerk-/Mount-Probleme: Readiness-Issues im Dashboard oder Status-API; ohne schreibbares Quarantäne-Verzeichnis sind File-Ops blockiert.
- PWA/Assets: `/manifest.webmanifest` und `/service-worker.js` müssen 200 liefern; Icons unter `/static/pwa/`.
