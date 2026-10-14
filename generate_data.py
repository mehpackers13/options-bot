"""
generate_data.py
================
Converts alerts_log.csv, bot.log, threshold_changes.log, and AI suggestions
into docs/data.json so the GitHub Pages dashboard always has fresh data.
Called automatically by GitHub Actions after every scan and morning analysis.
You can also run it manually:  python generate_data.py
"""

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from time_utils import parse_timestamp, last_completed_scan
from safe_state import atomic_json

BASE = Path(__file__).parent
DOCS = BASE / "docs"
DATA = BASE / "data"
DOCS.mkdir(exist_ok=True)


def read_alerts():
    path = BASE / "alerts_log.csv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return [row for row in csv.DictReader(f) if row.get("timestamp")]


def read_last_scan():
    path = BASE / "bot.log"
    if not path.exists():
        return "Never"
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    for line in reversed(lines):
        if any(kw in line for kw in ["Scan complete", "Scanning", "market closed"]):
            try:
                return line.split("]")[0].lstrip("[").strip()
            except Exception:
                pass
    return lines[-1].split("]")[0].lstrip("[").strip() if lines else "Unknown"


def read_threshold_changes():
    path = BASE / "threshold_changes.log"
    if not path.exists():
        return []
    return [l for l in path.read_text().splitlines() if l.strip()][-30:]


def read_ai_suggestions():
    path = DATA / "ai_suggestions.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def read_ai_weekly():
    path = DATA / "ai_weekly.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def calculate_stats(alerts):
    if not alerts:
        return {
            "total_alerts": 0, "overall_hit_rate": None,
            "rated_count": 0, "by_signal_type": {},
            "earnings_plays": 0,
        }

    rated = [a for a in alerts if a.get("outcome") in ("0", "1")]
    hits  = [a for a in rated  if a.get("outcome") == "1"]
    overall = round(len(hits) / len(rated) * 100, 1) if rated else None
    earnings_plays = sum(1 for a in alerts if a.get("is_earnings_play") in ("1", 1))

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
        "total_alerts":     len(alerts),
        "overall_hit_rate": overall,
        "rated_count":      len(rated),
        "by_signal_type":   by_signal,
        "earnings_plays":   earnings_plays,
    }


def read_unit_total(alerts):
    """Options bot: 1 unit = 1 correct signal (paper tracking). Returns running unit total."""
    rated = [a for a in alerts if a.get("outcome") in ("0", "1")]
    units = sum(1.0 if a["outcome"] == "1" else -1.0 for a in rated)
    return round(units, 1)


def read_today_alerts(alerts):
    """Return alerts from the last 24 hours."""
    cutoff = datetime.now().astimezone() - timedelta(hours=24)
    today = []
    for a in alerts:
        ts_str = a.get("timestamp", "")
        try:
            ts = parse_timestamp(ts_str, "America/New_York")
            if ts and cutoff <= ts <= datetime.now().astimezone():
                today.append(a)
        except Exception:
            pass
    return list(reversed(today))


def main():
    alerts    = read_alerts()
    last_scan = read_last_scan()
    changes   = read_threshold_changes()
    stats     = calculate_stats(alerts)
    ai_daily  = read_ai_suggestions()
    ai_weekly = read_ai_weekly()
    unit_total = read_unit_total(alerts)
    today_alerts = read_today_alerts(alerts)

    for row in alerts:
        stamp = parse_timestamp(row.get("timestamp"), "America/New_York")
        row["timestamp_iso"] = stamp.isoformat() if stamp else None
    recent = list(reversed(alerts[-50:]))

    data = {
        "generated_at":      datetime.utcnow().isoformat() + "Z",
        "last_scan":         last_scan,
        "last_scan_ts":      last_completed_scan(BASE / "bot.log", "America/New_York"),
        "stats":             stats,
        "unit_total":        unit_total,
        "today_alerts":      today_alerts,
        "alerts":            recent,
        "threshold_changes": changes,
        "ai_daily":          ai_daily,
        "ai_weekly":         ai_weekly,
    }

    out = DOCS / "data.json"
    atomic_json(out, data)

    print(
        f"✓ docs/data.json written — {len(recent)} alerts, "
        f"last scan: {last_scan}, "
        f"AI daily: {'yes' if ai_daily else 'no'}"
    )


if __name__ == "__main__":
    main()
