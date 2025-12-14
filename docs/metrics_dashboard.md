# Performance-Matrix / Diagnose-Dashboard

## Starten
- Page: `/metrics` (interne Auth nötig).
- Run-Auswahl: Dropdown „Run wählen“ (Standard = letzter Run). Nur Run-basiert, kein Zeitfenster-Sammelsurium mehr.
- Neuer Testlauf: Parameter (Anzahl, Extension, Mindestgröße) setzen, „Starten“. Run-ID wird angezeigt; Artefakt unter `data/metrics_runs/`.

## Metriken
- Run-basiert: alle Kennzahlen beziehen sich auf einen Test-Run (Events 1..N).
- Preview-Zeit pro Dokument (Timeline) + p50/p95 (Gesamt, TTFB, SMB First Read, Transfer).
- Durchsatz: Events/Minute im Run, Fehlerquote (HTTP >= 400).
- SMB: Latenz (p50/p95) und Transfer-Dauer, Durchsatz (MB/s) aus Events.
- System-Slots (während Run): CPU%, Load1, iowait%, RAM%, Swap, Net bytes (cumulative), Disk read/write bytes, Pagefaults (falls verfügbar).

## Ampel / Regeln
- Konfiguration: `config/metrics_thresholds.json` (Defaults in `app/metrics_config.py`).
- Relevante Keys:
  - `preview_p95_ms`, `preview_p50_ms`
  - `previews_per_min`
  - `error_rate`
  - `smb_latency_p95_ms`, `smb_latency_p50_ms`
  - `smb_throughput_mb_s`
  - `cpu_percent`, `cpu_load_per_core`
  - `mem_used_percent`, `swap_used_percent`
  - `io_wait_percent`
  - `disk_read_mb_s`, `disk_write_mb_s`, `net_throughput_mb_s`
- Grenzlogik: `warn`/`crit` = >= Schwelle (höher ist schlechter), `warn_below`/`crit_below` = < Schwelle (niedriger ist schlechter). Worst-Case bestimmt die Farbe pro Kategorie.

## Artefakte & Vergleich
- Jeder Testlauf erzeugt `data/metrics_runs/<run-id>.json` mit: Parametern, Umgebung (Host/OS/CPU/RAM/Mounts), Summary, Top-slow, Timeline, System-Slots, Diagnose (Ampel + Top-Ursachen + Belege).
- API: `/api/admin/metrics/runs` (Liste), `/api/admin/metrics/run/{id}` (Detail), `/api/admin/metrics/run_latest` (letzter Run).
- Frontend zeigt standardmäßig letzten Run, Wechsel über Dropdown.

## Rohdaten
- Details-Tab: Roh-Events des Runs (inkl. SMB/Transfer) und System-Slots-Tabelle.
- Run-Events-Endpoint bleibt verfügbar: `/api/admin/metrics/test_run_results?test_run_id=...`.
