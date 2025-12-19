# Admin-Always-On-Modus

Zweck: Für abgeschottete, vertrauenswürdige Umgebungen kann der Admin-Modus ohne Passwort-Dialog dauerhaft aktiv sein. Standard bleibt unverändert (Passwort-Overlay, kein persistenter Login).

## Aktivierung
- Env-Flag `ADMIN_ALWAYS_ON=true` setzen (Default: `false`).
- Docker Compose: Flag ist in `docker-compose.yml` und `.env(.example)` hinterlegt (`ADMIN_ALWAYS_ON=${ADMIN_ALWAYS_ON:-false}`).
- Das Flag ersetzt **nicht** das `APP_SECRET`. Alle API-Aufrufe brauchen weiterhin ein gültiges Secret.

## Verhalten
- Backend: `require_admin` gibt sofort `True` zurück, wenn `ADMIN_ALWAYS_ON` aktiv ist. Pfad-/Quarantäne-Guards und Dateirechte bleiben unverändert (keine erweiterten Schreibrechte).
- Admin-Status: `/api/admin/status` liefert `admin=true` und `admin_always_on=true`. Login/Logout sind im Always-On-Modus wirkungslos.
- Frontend: Admin-Overlay wird übersprungen, Admin-UI ist sofort sichtbar („Admin-Modus aktiv“), Admin-Button bleibt aktiv.

## Sicherheit
- Nur in vertrauenswürdigen Netzen/Deployments nutzen (z. B. isolierte Test-/Intranet-Umgebung).
- TLS/Reverse-Proxy und `APP_SECRET` bleiben Pflicht; keine Schwächung der Route-Gates oder File-Guards.
- Für produktive, geteilte Umgebungen weiterhin den Passwort-Flow nutzen (Default).

## Smoke/Tests
- Backend: Admin-Ops ohne Login sollten nur mit gesetztem `ADMIN_ALWAYS_ON` und gültigem `APP_SECRET` funktionieren.
- UI: Kein Admin-Overlay mehr, Button sofort aktiv; Admin-Aktionen (z. B. Rename/Delete/Quarantäne) müssen weiterhin funktionieren.
