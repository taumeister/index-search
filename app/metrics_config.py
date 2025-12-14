import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict


DEFAULT_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    "preview_p95_ms": {"warn": 2000, "crit": 4000},
    "preview_p50_ms": {"warn": 1000, "crit": 2000},
    "previews_per_min": {"warn_below": 10, "crit_below": 5},
    "error_rate": {"warn": 0.02, "crit": 0.05},
    "smb_latency_p95_ms": {"warn": 300, "crit": 700},
    "smb_latency_p50_ms": {"warn": 150, "crit": 400},
    "smb_throughput_mb_s": {"warn_below": 8, "crit_below": 4},
    "io_wait_percent": {"warn": 8, "crit": 15},
    "cpu_percent": {"warn": 75, "crit": 90},
    "cpu_load_per_core": {"warn": 0.9, "crit": 1.5},
    "mem_used_percent": {"warn": 80, "crit": 92},
    "swap_used_percent": {"warn": 5, "crit": 15},
    "disk_read_mb_s": {"warn_below": 5, "crit_below": 2},
    "disk_write_mb_s": {"warn_below": 5, "crit_below": 2},
    "net_throughput_mb_s": {"warn_below": 8, "crit_below": 4},
}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def load_thresholds(path: Path = Path("config/metrics_thresholds.json")) -> Dict[str, Dict[str, Any]]:
    """
    Lädt Grenzwerte aus JSON. Fehlende Werte fallen auf DEFAULT_THRESHOLDS zurück.
    """
    thresholds = deepcopy(DEFAULT_THRESHOLDS)
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                thresholds = _merge(thresholds, raw)
        except Exception:
            # Fallback auf Defaults
            pass
    return thresholds
