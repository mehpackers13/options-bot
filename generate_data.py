"""
generate_data.py
================
Converts alerts_log.csv, bot.log, and threshold_changes.log into
docs/data.json so the GitHub Pages dashboard always has fresh data.
Called automatically by GitHub Actions after every scan.
You can also run it manually:  python generate_data.py
"""

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).parent
DOCS = BASE / "docs"
DOCS.mkdir(exist_ok=True)


# ── Readers ────────────────────────────────────────────────────────────────────

def read_alerts():
    path = BASE / "alerts_log.csv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return [row for row in reader if row.get("timestamp")]


def read_last_scan():
    path = BASE / "bot.log"
    if not path.exists():
        return "Never"
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    for line in reversed(lines):
        if "Scan complete" in line or "Scanning" in line or "market closed" in line.lower():
            try:
                return line.split("]")[0].lstrip("[").strip()
            except Exception:
                pass
    if lines:
        try:
            return lines[-1].split("]")[0].lstrip("[").strip()
        except Exception:
            pass
    return "Unknown"


def read_threshold_changes():
    path = BASE / "threshold_changes.log"
    if not path.exists():
        return []
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    return lines[-30:]   # most recent 30 lines


# ── Stats ──────────────────────────────────────────────────────────────────────

def calculate_stats(alerts):
    if not alerts:
        return {"total_alerts": 0, "overall_hit_rate": None, "rated_count": 0, "by_signal_type": {}}

    rated = [a for a in alerts if a.get("outcome") in ("0", "1")]
    hits  = [a for a in rated  if a.get("outcome") == "1"]
    overall_hit_rate = round(len(hits) / len(rated) * 100, 1) if rated else None

    by_type = defaultdict(lambda: {"total": 0, "rated": 0, "hits": 0})
    for a in alerts:
        st = a.get("signal_type", "unknown")
        by_type[st]["total"] += 1
        if a.get("outcome") in ("0", "1"):
            by_type[st]["rated"] += 1
            if a.get("outcome") == "1":
                by_type[st]["hits"] += 1

    by_signal = {
        st: {
            "total":    d["total"],
            "rated":    d["rated"],
            "hits":     d["hits"],
            "hit_rate": round(d["hits"] / d["rated"] * 100, 1) if d["rated"] > 0 else None,
        }
        for st, d in by_type.items()
    }

    return {
        "total_alerts":    len(alerts),
        "overall_hit_rate": overall_hit_rate,
        "rated_count":     len(rated),
        "by_signal_type":  by_signal,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    alerts    = read_alerts()
    last_scan = read_last_scan()
    changes   = read_threshold_changes()
    stats     = calculate_stats(alerts)

    # Most recent 50, newest first
    recent = list(reversed(alerts[-50:]))

    data = {
        "generated_at":      datetime.utcnow().isoformat() + "Z",
        "last_scan":         last_scan,
        "stats":             stats,
        "alerts":            recent,
        "threshold_changes": changes,
    }

    out = DOCS / "data.json"
    with open(out, "w") as f:
        json.dump(data, f, indent=2)

    print(f"✓ docs/data.json written — {len(recent)} alerts, last scan: {last_scan}")


if __name__ == "__main__":
    main()
