# Neuaufbau des Such-Index

So setzt du den Index zurück und baust ihn neu auf. Dabei gehen alle Treffer/Dokumenteinträge verloren.

1) Container anhalten (optional, aber sicherer)
   ```bash
   docker compose down
   ```

2) Indexdatei + WAL/SHM löschen
   ```bash
   rm -f data/index.db data/index.db-wal data/index.db-shm
   ```

3) Container starten (Build nur bei Codeänderungen nötig)
   ```bash
   docker compose up -d
   ```

4) Neu indexieren
   ```bash
   docker compose exec web python -m app.indexer.index_lauf_service
   ```

Hinweise
- Nach dem Löschen ist der Index leer, bis der Lauf abgeschlossen ist.
- Falls du statt Löschen leeren willst: In SQLite `DELETE FROM documents; DELETE FROM documents_fts; VACUUM;`, anschließend Indexlauf starten.
