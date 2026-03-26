"""
EARNINGS CALENDAR
=================
Checks upcoming earnings dates so the bot can:
  • Flag earnings plays (earnings within 24h + unusual activity = intentional setup)
  • Suppress noise from random activity near earnings that isn't an earnings play
"""

import datetime
from typing import Optional, Tuple

import pytz
import yfinance as yf

ET = pytz.timezone("America/New_York")


def get_next_earnings(ticker: str) -> Optional[datetime.date]:
    """Return the next scheduled earnings date, or None if unknown."""
    try:
        t   = yf.Ticker(ticker)
        cal = t.calendar

        if cal is None:
            return None

        # yfinance returns a dict or DataFrame depending on version
        if hasattr(cal, "iloc"):
            # DataFrame shape: columns are dates, index has "Earnings Date"
            if "Earnings Date" in cal.index:
                raw = cal.loc["Earnings Date"].iloc[0]
                if hasattr(raw, "date"):
                    return raw.date()
            return None

        if isinstance(cal, dict):
            raw = cal.get("Earnings Date")
            if not raw:
                return None
            # May be a list
            if isinstance(raw, list):
                raw = raw[0] if raw else None
            if raw is None:
                return None
            if hasattr(raw, "date"):
                return raw.date()
            if isinstance(raw, str):
                return datetime.date.fromisoformat(raw[:10])
    except Exception:
        pass
    return None


def earnings_within_hours(ticker: str, hours: int = 24) -> Tuple[bool, Optional[datetime.date]]:
    """Returns (True, date) if the next earnings are within `hours` hours from now."""
    date = get_next_earnings(ticker)
    if date is None:
        return False, None

    now       = datetime.datetime.now(ET)
    today     = now.date()
    delta_days = (date - today).days
    hours_away = delta_days * 24 - now.hour   # rough estimate

    return (-24 <= hours_away <= hours), date


def is_earnings_play(ticker: str) -> Tuple[bool, Optional[datetime.date]]:
    """
    True when earnings are within 24 hours.
    In this window, unusual options activity is EXPECTED and should be
    treated as an earnings play — not generic unusual activity.
    """
    return earnings_within_hours(ticker, hours=24)


def earnings_in_next_week(ticker: str) -> Tuple[bool, Optional[datetime.date]]:
    """True if earnings are within 7 days."""
    return earnings_within_hours(ticker, hours=168)
