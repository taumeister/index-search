#!/bin/sh
set -euo pipefail

DB_PATH=${1:-/app/data/index.db}

if [ ! -f "$DB_PATH" ]; then
  echo "Database not found: $DB_PATH"
  exit 1
fi

python - "$DB_PATH" <<'PY'
import os
import sqlite3
import sys

db = sys.argv[1]
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row

print("== DB Summary ==")
print(f"DB path: {db}")
total_docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
print(f"Documents total: {total_docs}")

last_run = None
last_run = con.execute(
    "SELECT id, started_at, finished_at, status, scanned_files, added, updated, removed, errors, message "
    "FROM index_runs ORDER BY started_at DESC LIMIT 1"
).fetchone()
if last_run:
    print("Last run:")
    for key in ("id", "started_at", "finished_at", "status", "scanned_files", "added", "updated", "removed", "errors", "message"):
        print(f"  {key}: {last_run[key]}")
else:
    print("Last run: none recorded")

if last_run:
    print("\n== Last run file errors ==")
    errs = con.execute(
        "SELECT path, error_type, message FROM file_errors WHERE run_id = ? ORDER BY created_at DESC LIMIT 50",
        (last_run["id"],),
    ).fetchall()
    if errs:
        for row in errs:
            print(f"path={row['path']} error={row['error_type']} msg={row['message']}")
    else:
        print("none")

missing = []
for row in con.execute("SELECT id, source, path FROM documents"):
    if not os.path.exists(row["path"]):
        missing.append(row)

print("\n== Missing files (filesystem check) ==")
print(f"Missing count: {len(missing)}")
limit = 200
for idx, row in enumerate(missing[:limit], start=1):
    print(f"{idx:03d}: id={row['id']} source={row['source']} path={row['path']}")
if len(missing) > limit:
    print(f"... truncated to {limit} of {len(missing)}")
if not missing:
    print("No missing files detected.")

if last_run and last_run["started_at"]:
    import datetime
    try:
        start_ts = datetime.datetime.fromisoformat(last_run["started_at"]).timestamp()
    except Exception:
        start_ts = None
    if start_ts:
        print("\n== Candidates added/updated since last run start (by mtime) ==")
        candidates = con.execute(
            "SELECT id, source, path, filename, extension, mtime "
            "FROM documents WHERE mtime >= ? ORDER BY mtime DESC LIMIT 200",
            (start_ts,),
        ).fetchall()
        if candidates:
            for row in candidates:
                print(f"id={row['id']} source={row['source']} mtime={row['mtime']} path={row['path']}")
        else:
            print("none")

print("\n== Recently modified documents (top 50 by mtime) ==")
recent = con.execute(
    "SELECT id, source, path, filename, extension, mtime "
    "FROM documents ORDER BY mtime DESC LIMIT 50"
).fetchall()
for row in recent:
    print(f"id={row['id']} source={row['source']} mtime={row['mtime']} path={row['path']}")
PY
