# Konfigurations-Referenz

Quelle: `.env.example`, `docker-compose.yml`, Backend-Defaults.

| Variable | Default/Beispiel | Beschreibung |
| --- | --- | --- |
| `APP_SECRET` | generiert oder aus `.env` | Obligatorisch für alle API-Calls (`X-App-Secret`). |
| `ADMIN_PASSWORD` | `admin` | Passwort für `/api/admin/login` (Cookie `admin_session`). |
| `ADMIN_ALWAYS_ON` | `false` | Schaltet Admin-Checks ab; nur in vertrauenswürdigen Umgebungen nutzen. |
| `TZ` | `Europe/Berlin` | Zeitzone für Logs/Jobs. |
| `APP_HTTP_PORT` | `8010` (Compose) | Host-Port für den Web-Service → Container-Port `8000`. |
| `DATA_HOST_PATH` | `/home/tom/projekte/99_index` | Host-Pfad, der nach `/data` gemountet wird. |
| `DATA_CONTAINER_PATH` | `/data` | Basispfad im Container; Quellen müssen darunter liegen. |
| `INDEX_ROOTS` | leer | Optionale Root-Liste (`<pfad>:<label>`), sonst Verwaltung über UI/DB. |
| `INDEX_WORKER_COUNT` | `2` | Anzahl paralleler Index-Worker. |
| `INDEX_MAX_FILE_SIZE_MB` | `0` | 0 = kein Limit; sonst Dateien ab dieser Größe überspringen. |
| `INDEX_EXCLUDE_DIRS` | `.quarantine` | Kommagetrennte Ordner, die beim Scan ignoriert werden. |
| `QUARANTINE_RETENTION_DAYS` | `30` | Aufbewahrungstage für Quarantäne-Dateien. |
| `QUARANTINE_CLEANUP_SCHEDULE` | `daily` | Cleanup-Intervall (`daily`, `hourly`, `off`). |
| `QUARANTINE_CLEANUP_DRYRUN` | `false` | Cleanup nur simulieren, nichts löschen. |
| `LOG_LEVEL` | `INFO` | Logging-Level (Uvicorn/Backend). |
| `LOG_DIR` | `logs` | Verzeichnis für Lauf-Logs. |
| `LOG_ROTATION_MB` | `30` | Schwelle für Log-Rotation. |
| `SMTP_HOST` | `smtp.gmail.com` | SMTP-Server für Reports. |
| `SMTP_PORT` | `587` | SMTP-Port. |
| `SMTP_USE_TLS` | `true` | TLS für SMTP. |
| `SMTP_USER`/`SMTP_PASS` | Mail/Passwort | Zugangsdaten für SMTP. |
| `SMTP_FROM` | `index-search@unixuser.de` | Absender-Adresse. |
| `SMTP_TO` | `taumeister@gmail.com` | Empfänger-Adresse (Reports). |
| `SEND_REPORT_ENABLED` | `0` | Report-Versand aktivieren (sofern SMTP gesetzt). |
| `FEEDBACK_ENABLED` | `true` | Feedback-Overlay und API aktivieren. |
| `FEEDBACK_TO` | `taumeister@gmail.com` | Zieladresse für Feedback-E-Mails. |
| `APP_TITLE` | leer | Branding-Titel im Header/Über-Overlay. |
| `APP_SLOGAN` | leer | Optionaler Slogan im Header/Über-Overlay. |

## Hinweise
- `.env.example` enthält produktionsnahe Defaults; sensible Werte für `APP_SECRET`, `ADMIN_PASSWORD`, SMTP sollten überschrieben werden.
- Quellen/Roots werden bevorzugt über das Dashboard verwaltet; `INDEX_ROOTS` dient nur als Initialisierung/Fallback.
- File-Ops/Quarantäne benötigen Schreibrechte unterhalb von `<root>/.quarantine/`.
- Der Auto-Index-Scheduler speichert Zeitplan/Status in `config/config.db`; die oben genannten ENV steuern nur Basisverhalten.
