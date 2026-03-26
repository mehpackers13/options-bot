"""
SIGNAL FILTER — FOUR-GATE SYSTEM
==================================
Every raw signal must pass ALL four gates before the bot fires an alert.
If anything fails, the bot stays completely silent.

Gate 1 — Volume: options volume >= 3x the 20-day average
Gate 2 — Historical pattern: signal type hit rate >= 35% (once 20+ rated alerts exist)
Gate 3 — Earnings check: suppress noise near earnings UNLESS it IS an earnings play
Gate 4 — Confidence score: composite score must be >= 70/100
"""

import csv
import datetime
from pathlib import Path
from typing import Optional, Tuple

BASE      = Path(__file__).parent
ALERTS_LOG = BASE / "alerts_log.csv"

MIN_RATED_FOR_PATTERN_GATE = 20
MIN_SAMPLES_PER_TYPE       = 5
CONFIDENCE_THRESHOLD       = 70
HIT_RATE_FLOOR             = 0.35


def _load_rated_alerts() -> list:
    if not ALERTS_LOG.exists():
        return []
    rated = []
    try:
        with open(ALERTS_LOG, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("outcome") in ("0", "1"):
                    rated.append(row)
    except Exception:
        pass
    return rated


def _hit_rate(signal_type: str, rated: list) -> Optional[float]:
    matching = [r for r in rated if r.get("signal_type") == signal_type]
    if len(matching) < MIN_SAMPLES_PER_TYPE:
        return None
    hits = sum(1 for r in matching if r.get("outcome") == "1")
    return hits / len(matching)


def compute_confidence(
    signal_type: str,
    volume_ratio: float,
    iv_change_pct: Optional[float],
    pc_ratio: Optional[float],
    is_earnings_play: bool,
    has_earnings_soon: bool,
    rated_alerts: list,
) -> int:
    """
    Compute a 0–100 confidence score based on signal strength + history.
    Components:
      Base                   50
      Volume strength        +6 / +12 / +20
      Historical hit rate    -20 to +20
      IV magnitude           +3 / +6 / +10
      P/C ratio extreme      +3 / +6 / +10
      Earnings play bonus    +8
      Earnings noise penalty -15
    """
    score = 50

    # Volume strength
    if volume_ratio >= 10:
        score += 20
    elif volume_ratio >= 5:
        score += 12
    elif volume_ratio >= 3:
        score += 6

    # Historical hit rate for this signal type
    hr = _hit_rate(signal_type, rated_alerts)
    if hr is not None:
        if hr >= 0.65:
            score += 20
        elif hr >= 0.55:
            score += 12
        elif hr >= 0.45:
            score += 5
        elif hr >= 0.35:
            score -= 5
        else:
            score -= 20

    # IV magnitude
    if iv_change_pct is not None:
        if iv_change_pct >= 50:
            score += 10
        elif iv_change_pct >= 30:
            score += 6
        elif iv_change_pct >= 20:
            score += 3

    # Put/call ratio extreme
    if pc_ratio is not None and pc_ratio > 0:
        if pc_ratio >= 3.0 or pc_ratio <= 0.33:
            score += 10
        elif pc_ratio >= 2.5 or pc_ratio <= 0.40:
            score += 6
        elif pc_ratio >= 2.0 or pc_ratio <= 0.50:
            score += 3

    # Earnings adjustments
    if is_earnings_play:
        score += 8
    elif has_earnings_soon:
        score -= 15

    return max(0, min(100, score))


def check_all_gates(
    ticker: str,
    signal_type: str,
    volume_ratio: float,
    iv_change_pct: Optional[float] = None,
    pc_ratio: Optional[float] = None,
    is_earnings_play: bool = False,
    has_earnings_soon: bool = False,
) -> Tuple[bool, int, str]:
    """
    Run all four gates.
    Returns (passes: bool, confidence: int, reason: str).
    """
    rated = _load_rated_alerts()

    # ── Gate 1: Volume must be >= 3x the 20-day average ──────────────────────
    if volume_ratio < 3.0:
        return (
            False, 0,
            f"Gate 1 FAIL — volume ratio {volume_ratio:.1f}x is below the 3x minimum"
        )

    # ── Gate 2: Historical pattern — once we have 20+ rated alerts ───────────
    if len(rated) >= MIN_RATED_FOR_PATTERN_GATE:
        hr = _hit_rate(signal_type, rated)
        if hr is not None and hr < HIT_RATE_FLOOR:
            return (
                False, 0,
                f"Gate 2 FAIL — {signal_type} has only {hr*100:.0f}% hit rate "
                f"(minimum {HIT_RATE_FLOOR*100:.0f}%) — pausing this signal type"
            )

    # ── Gate 3: Earnings check — suppress ambiguous pre-earnings noise ────────
    if has_earnings_soon and not is_earnings_play:
        return (
            False, 0,
            f"Gate 3 FAIL — earnings within 24h but signal is not classified "
            f"as an earnings play (too noisy, skipping)"
        )

    # ── Gate 4: Confidence score >= 70 ───────────────────────────────────────
    confidence = compute_confidence(
        signal_type, volume_ratio, iv_change_pct, pc_ratio,
        is_earnings_play, has_earnings_soon, rated
    )
    if confidence < CONFIDENCE_THRESHOLD:
        return (
            False, confidence,
            f"Gate 4 FAIL — confidence {confidence}/100 is below "
            f"the {CONFIDENCE_THRESHOLD} threshold"
        )

    return True, confidence, "All gates passed"
