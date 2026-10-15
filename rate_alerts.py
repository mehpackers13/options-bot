"""
RATE ALERTS
===========
Scores every unrated row in alerts_log.csv once the alert has had enough
time to play out. An alert is a "hit" (outcome=1) when the underlying's
close price moved in the predicted direction by at least MIN_MOVE within
the RATING_WINDOW_DAYS trading days after the alert.

Signal → prediction mapping:
  put_call_low (bullish skew)   → price UP   >= MIN_MOVE%
  put_call_high (bearish skew)  → price DOWN >= MIN_MOVE%
  volume_spike                   → |move|    >= MIN_MOVE%   (direction-agnostic)
  iv_jump                        → |move|    >= MIN_MOVE%   (vol expected to realize)

Runs daily from run_4pm.py so new ratings land before self_improve looks at
the data overnight. Idempotent — only touches rows with blank outcome AND
old enough to be ratable.
"""
import csv
import datetime
from pathlib import Path
from typing import Optional

try:
    import yfinance as yf
    _YF_OK = True
except Exception:
    _YF_OK = False

from bot import log


ALERTS_LOG         = Path(__file__).parent / "alerts_log.csv"
RATING_WINDOW_DAYS = 5         # trading days to let the move play out
MIN_MOVE_PCT       = 3.0       # % move needed to call it a hit


def _parse_ts(s: str) -> Optional[datetime.datetime]:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt)
        except Exception:
            pass
    return None


def _price_move_pct(ticker: str, alert_date: datetime.date) -> Optional[float]:
    """
    Return the max absolute signed move % from alert_date close through
    RATING_WINDOW_DAYS trading days later.  Positive = up, negative = down.
    Returns None if yfinance has no data or the window hasn't elapsed yet.
    """
    if not _YF_OK:
        return None
    try:
        # Pull a wider window to be safe against weekends/holidays
        start = alert_date - datetime.timedelta(days=1)
        end   = alert_date + datetime.timedelta(days=RATING_WINDOW_DAYS + 5)
        hist  = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat())
        if hist is None or hist.empty:
            return None
        closes = hist["Close"].tolist()
        if len(closes) < 2:
            return None
        base = closes[0]
        # look at the max up-move and max down-move over the window
        window = closes[1 : RATING_WINDOW_DAYS + 1]
        if not window:
            return None
        up   = (max(window) - base) / base * 100
        down = (min(window) - base) / base * 100
        # return the larger-magnitude move
        return up if abs(up) >= abs(down) else down
    except Exception as exc:
        log(f"rate_alerts: price lookup failed for {ticker}: {exc}", "WARN")
        return None


def _grade(signal_type: str, move_pct: float) -> int:
    """Return 1 if the signal's prediction hit, else 0."""
    s = (signal_type or "").lower()
    if s == "put_call_low":                           # bullish
        return 1 if move_pct >=  MIN_MOVE_PCT else 0
    if s == "put_call_high":                          # bearish
        return 1 if move_pct <= -MIN_MOVE_PCT else 0
    if s in ("volume_spike", "iv_jump"):              # direction-agnostic
        return 1 if abs(move_pct) >= MIN_MOVE_PCT else 0
    # Unknown signal types: skip
    return -1


def run() -> dict:
    """
    Walk alerts_log.csv, grade every unrated alert old enough to resolve.
    Writes outcomes in place. Returns {graded, hits, misses, skipped}.
    """
    if not ALERTS_LOG.exists():
        log("rate_alerts: no alerts_log.csv — nothing to grade", "INFO")
        return {"graded": 0, "hits": 0, "misses": 0, "skipped": 0}

    with open(ALERTS_LOG, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return {"graded": 0, "hits": 0, "misses": 0, "skipped": 0}

    fieldnames = list(rows[0].keys())
    if "outcome" not in fieldnames:
        fieldnames.append("outcome")

    now         = datetime.datetime.utcnow()
    cutoff      = now - datetime.timedelta(days=RATING_WINDOW_DAYS + 2)  # need window to have elapsed
    graded, hits, misses, skipped = 0, 0, 0, 0

    for r in rows:
        if (r.get("outcome") or "").strip() != "":
            continue
        ts = _parse_ts(r.get("timestamp", ""))
        if not ts:
            skipped += 1
            continue
        if ts > cutoff:
            # not yet ready — alert needs its window to pass
            skipped += 1
            continue
        ticker = (r.get("ticker") or "").strip()
        if not ticker:
            skipped += 1
            continue
        move = _price_move_pct(ticker, ts.date())
        if move is None:
            skipped += 1
            continue
        grade = _grade(r.get("signal_type", ""), move)
        if grade < 0:
            skipped += 1
            continue
        r["outcome"] = str(grade)
        graded += 1
        if grade == 1:
            hits += 1
        else:
            misses += 1
        log(f"  Rated {r.get('timestamp','?')[:16]} {ticker:5} "
            f"{r.get('signal_type',''):15} move={move:+.1f}% → "
            f"{'✅ hit' if grade else '❌ miss'}")

    if graded > 0:
        with open(ALERTS_LOG, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                r.pop(None, None)
                w.writerow(r)
        log(f"rate_alerts: graded {graded} alerts ({hits} hits / {misses} misses), {skipped} not ready")

    return {"graded": graded, "hits": hits, "misses": misses, "skipped": skipped}


if __name__ == "__main__":
    run()
