"""Atomic JSON state writes and validated threshold loading."""
import json
import math
import os
import tempfile
from pathlib import Path

LIMITS = {
    "volume_spike_multiplier": (3.0, 10.0),
    "iv_jump_percent": (10.0, 60.0),
    "put_call_ratio_high": (1.2, 5.0),
    "put_call_ratio_low": (0.1, 0.8),
}

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def validated_thresholds(path, defaults):
    result = defaults.copy()
    if not Path(path).exists():
        return result
    saved = json.loads(Path(path).read_text())
    if not isinstance(saved, dict):
        raise ValueError("Threshold state must be a JSON object")
    for key, (low, high) in LIMITS.items():
        value = saved.get(key, result[key])
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Invalid threshold: {key}")
        result[key] = max(low, min(high, value))
    return result
