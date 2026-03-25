"""
SELF-IMPROVEMENT ENGINE
========================
Reads your alert history, calculates which signals worked, and auto-tunes thresholds.
Runs automatically each morning before market open (8:00–9:25am ET).
You can also run it manually any time: python self_improve.py
"""

import csv
import datetime
import json
from pathlib import Path

import pytz

import config

BASE_DIR        = Path(__file__).parent
DATA_DIR        = BASE_DIR / "data"
ALERTS_LOG      = BASE_DIR / "alerts_log.csv"
THRESHOLDS_FILE = DATA_DIR / "thresholds.json"
CHANGES_LOG     = BASE_DIR / "threshold_changes.log"

ET = pytz.timezone("America/New_York")

# Conservative adjustment step — thresholds move 10 % per analysis cycle
ADJUSTMENT_STEP = 0.10

# We try to keep hit rates in this range:
#   Below TARGET_MIN → too many false positives → raise threshold (be stricter)
#   Above TARGET_MAX → almost nothing fires   → lower threshold (be more sensitive)
TARGET_MIN_HIT_RATE = 0.45
TARGET_MAX_HIT_RATE = 0.80

# Hard floors/ceilings so the bot never goes to extremes
LIMITS = {
    "volume_spike_multiplier": (1.5, 10.0),
    "iv_jump_percent":         (10.0, 60.0),
    "put_call_ratio_high":     (1.2, 5.0),
    "put_call_ratio_low":      (0.1, 0.8),
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_thresholds() -> dict:
    if THRESHOLDS_FILE.exists():
        with open(THRESHOLDS_FILE) as f:
            return json.load(f)
    return config.DEFAULT_THRESHOLDS.copy()


def save_thresholds(thresholds: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with open(THRESHOLDS_FILE, "w") as f:
        json.dump(thresholds, f, indent=2)


def _log_change(message: str) -> None:
    ts   = datetime.datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
    line = f"[{ts}] {message}"
    print(line)
    with open(CHANGES_LOG, "a") as f:
        f.write(line + "\n")


# ── Alert history loading ──────────────────────────────────────────────────────

def load_rated_alerts() -> list:
    """
    Return all rows from alerts_log.csv where 'outcome' is 1 (correct) or 0 (wrong).
    Rows where outcome is blank are not counted — they haven't been rated yet.
    """
    if not ALERTS_LOG.exists():
        return []

    rated = []
    with open(ALERTS_LOG, newline="") as f:
        for row in csv.DictReader(f):
            outcome = row.get("outcome", "").strip()
            if outcome in ("1", "0"):
                row["_outcome"] = int(outcome)
                rated.append(row)
    return rated


# ── Statistics ─────────────────────────────────────────────────────────────────

def calculate_signal_stats(rated: list) -> dict:
    """
    Group alerts by signal_type and compute:
      - total    : number of rated alerts
      - hits     : alerts where outcome == 1
      - hit_rate : hits / total
      - avg_value: average signal_value (how far above threshold the signal was)
    """
    stats: dict = {}
    for row in rated:
        sig = row["signal_type"]
        if sig not in stats:
            stats[sig] = {"total": 0, "hits": 0, "values": []}
        stats[sig]["total"] += 1
        stats[sig]["hits"]  += row["_outcome"]
        try:
            stats[sig]["values"].append(float(row["signal_value"]))
        except (ValueError, KeyError):
            pass

    for sig, s in stats.items():
        s["hit_rate"]  = s["hits"] / s["total"] if s["total"] > 0 else 0.0
        s["avg_value"] = sum(s["values"]) / len(s["values"]) if s["values"] else 0.0

    return stats


# ── Threshold adjustment ───────────────────────────────────────────────────────

def _clamp(value: float, key: str) -> float:
    lo, hi = LIMITS[key]
    return max(lo, min(hi, value))


def _adjust(current: float, direction: str, key: str) -> float:
    """Increase or decrease current by ADJUSTMENT_STEP, then clamp to limits."""
    if direction == "up":
        new = current * (1 + ADJUSTMENT_STEP)
    else:
        new = current * (1 - ADJUSTMENT_STEP)
    return round(_clamp(new, key), 2)


def adjust_and_save(stats: dict, thresholds: dict) -> int:
    """
    Apply threshold adjustments based on signal stats.
    Returns the number of changes made.
    """
    changes = 0

    def maybe_adjust(sig_key: str, threshold_key: str, when_low: str, when_high: str,
                     min_samples: int = 5) -> None:
        nonlocal changes
        if sig_key not in stats:
            return
        s = stats[sig_key]
        if s["total"] < min_samples:
            print(f"  {sig_key}: only {s['total']} rated samples — need {min_samples}+, skipping")
            return

        current   = thresholds[threshold_key]
        hit_rate  = s["hit_rate"]
        direction = None
        reason    = ""

        if hit_rate < TARGET_MIN_HIT_RATE:
            direction = when_low
            reason = (
                f"hit rate {hit_rate:.0%} is below {TARGET_MIN_HIT_RATE:.0%} target "
                f"({s['hits']}/{s['total']} correct) — tightening threshold"
            )
        elif hit_rate > TARGET_MAX_HIT_RATE:
            direction = when_high
            reason = (
                f"hit rate {hit_rate:.0%} is above {TARGET_MAX_HIT_RATE:.0%} target "
                f"({s['hits']}/{s['total']} correct) — loosening threshold to catch more"
            )

        if direction:
            new_val = _adjust(current, direction, threshold_key)
            if new_val != current:
                thresholds[threshold_key] = new_val
                _log_change(
                    f"CHANGE  {threshold_key}: {current} → {new_val}  |  {reason}"
                )
                changes += 1
            else:
                print(f"  {threshold_key}: already at limit, no change")

    # ── Volume spike ──────────────────────────────────────────────────────────
    # Low hit rate → false positives → raise multiplier (harder to trigger)
    # High hit rate → accurate → lower multiplier (fire more often)
    maybe_adjust("volume_spike", "volume_spike_multiplier",
                 when_low="up", when_high="down")

    # ── IV jump ───────────────────────────────────────────────────────────────
    maybe_adjust("iv_jump", "iv_jump_percent",
                 when_low="up", when_high="down")

    # ── Bearish put/call ──────────────────────────────────────────────────────
    # Low hit rate → lower the ratio bar → raise threshold (require higher ratio)
    maybe_adjust("put_call_high", "put_call_ratio_high",
                 when_low="up", when_high="down")

    # ── Bullish put/call ──────────────────────────────────────────────────────
    # Low hit rate → ratio was too generous → lower threshold (require ratio closer to 0)
    maybe_adjust("put_call_low", "put_call_ratio_low",
                 when_low="down", when_high="up")

    return changes


# ── Main entry point ───────────────────────────────────────────────────────────

def run_morning_analysis() -> None:
    """
    Full self-improvement cycle. Called by bot.py each morning, or run manually.
    """
    print("\n" + "=" * 60)
    print("  MORNING SELF-IMPROVEMENT ANALYSIS")
    print(f"  {datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S ET')}")
    print("=" * 60)

    rated = load_rated_alerts()
    print(f"\n  Rated alerts found: {len(rated)}")

    if len(rated) < config.MIN_ALERTS_FOR_IMPROVEMENT:
        remaining = config.MIN_ALERTS_FOR_IMPROVEMENT - len(rated)
        print(
            f"\n  Need {remaining} more rated alerts before auto-tuning kicks in.\n"
            f"  Open alerts_log.csv and fill in the 'outcome' column:\n"
            f"    1 = the alert was correct (price moved as expected)\n"
            f"    0 = the alert was a false positive\n"
        )
        print("=" * 60 + "\n")
        return

    stats = calculate_signal_stats(rated)
    print("\n  Signal performance:")
    for sig, s in stats.items():
        bar = "█" * int(s["hit_rate"] * 10) + "░" * (10 - int(s["hit_rate"] * 10))
        print(f"    {sig:<25} {bar}  {s['hit_rate']:.0%}  ({s['hits']}/{s['total']})")

    thresholds = load_thresholds()
    print("\n  Checking thresholds ...")
    changes = adjust_and_save(stats, thresholds)

    if changes > 0:
        save_thresholds(thresholds)
        _log_change(
            f"SESSION END — {changes} change(s) saved. "
            f"New thresholds: {json.dumps(thresholds)}"
        )
        print(f"\n  {changes} threshold(s) updated. Details in threshold_changes.log")
    else:
        print("\n  All thresholds look healthy — no changes needed.")

    print("\n  Current thresholds:")
    for k, v in thresholds.items():
        lo, hi = LIMITS[k]
        print(f"    {k:<35} {v}  (range {lo}–{hi})")

    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_morning_analysis()
