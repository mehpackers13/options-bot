"""
run_4pm.py — 4pm ET daily market close summary.
Runs via GitHub Actions at 4pm ET (20:00 UTC) Monday–Friday.
Sends: current VIX, options market mood, alerts fired today, nearest miss.
"""

import csv
import datetime
from pathlib import Path

import pytz

import config
import data_sources
from bot import fetch_vix, _send_4pm_summary, log

ET        = pytz.timezone("America/New_York")
ALERTS_LOG = Path(__file__).parent / "alerts_log.csv"


def _count_alerts_today() -> tuple:
    """Return (alerts_today, nearest_miss_label) from alerts_log.csv."""
    if not ALERTS_LOG.exists():
        return 0, None
    today_str = datetime.datetime.now(ET).strftime("%Y-%m-%d")
    count    = 0
    best_conf = -1
    nearest  = None
    try:
        with open(ALERTS_LOG, newline="") as f:
            for row in csv.DictReader(f):
                ts = row.get("timestamp", "")
                if ts.startswith(today_str):
                    count += 1
        # nearest miss isn't stored in CSV — show top alert instead
    except Exception:
        pass
    return count, nearest


def main() -> None:
    now = datetime.datetime.now(ET)
    log(f"4pm daily summary — {now.strftime('%Y-%m-%d %H:%M ET')}")

    data_sources.init()

    vix_now = fetch_vix()
    alerts_today, _ = _count_alerts_today()

    _send_4pm_summary(vix_now, alerts_today, nearest_miss=None)
    log("4pm summary complete")


if __name__ == "__main__":
    main()
