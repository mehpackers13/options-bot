"""
DATA SOURCES
============
Tries Robinhood first for real-time data.
Falls back to yfinance automatically if Robinhood is unavailable or fails.
Credentials come from environment variables (GitHub Secrets):
  ROBINHOOD_USERNAME  — your Robinhood email
  ROBINHOOD_PASSWORD  — your Robinhood password
"""

import os
import time
from typing import Optional

import pandas as pd
import yfinance as yf

_use_robinhood: bool = False
_rh_login_attempted: bool = False


def _try_robinhood_login() -> bool:
    global _use_robinhood, _rh_login_attempted
    if _rh_login_attempted:
        return _use_robinhood
    _rh_login_attempted = True

    username = os.environ.get("ROBINHOOD_USERNAME", "")
    password = os.environ.get("ROBINHOOD_PASSWORD", "")
    if not username or not password:
        print("[data_sources] No Robinhood credentials — using yfinance")
        _use_robinhood = False
        return False

    try:
        import robin_stocks.robinhood as rh  # noqa: F401
        rh.login(
            username, password,
            expiresIn=86400,
            store_session=True,
            by_sms=False,        # avoid blocking on MFA prompt
        )
        _use_robinhood = True
        print("[data_sources] Robinhood login OK — using real-time data")
        return True
    except Exception as exc:
        print(f"[data_sources] Robinhood unavailable ({exc}) — using yfinance")
        _use_robinhood = False
        return False


def init() -> None:
    """Call once at startup to attempt Robinhood login."""
    _try_robinhood_login()


# ── Price ───────────────────────────────────────────────────────────────────────

def get_current_price(ticker: str) -> Optional[float]:
    if _use_robinhood:
        try:
            import robin_stocks.robinhood as rh
            prices = rh.stocks.get_latest_price(ticker)
            if prices and prices[0]:
                return float(prices[0])
        except Exception:
            pass
    # yfinance fallback
    try:
        t = yf.Ticker(ticker)
        price = t.fast_info.last_price
        if price and price > 0:
            return float(price)
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


# ── Options chain ───────────────────────────────────────────────────────────────

def get_options_chain(ticker: str, num_expirations: int = 3) -> Optional[dict]:
    """
    Returns a dict:
      {
        "expirations": [{"expiry": str, "calls": DataFrame, "puts": DataFrame}, ...],
        "source": "robinhood" | "yfinance"
      }
    """
    if _use_robinhood:
        try:
            return _rh_options_chain(ticker, num_expirations)
        except Exception as exc:
            print(f"[data_sources] RH options chain failed ({exc}) — falling back to yfinance")

    return _yf_options_chain(ticker, num_expirations)


def _rh_options_chain(ticker: str, num_expirations: int) -> Optional[dict]:
    import robin_stocks.robinhood as rh

    chain_info = rh.options.get_chains(ticker)
    if not chain_info:
        return None
    exp_dates = chain_info.get("expiration_dates", [])
    if not exp_dates:
        return None

    expirations = []
    for exp in exp_dates[:num_expirations]:
        calls_raw = rh.options.find_options_by_expiration(ticker, exp, optionType="call")
        puts_raw  = rh.options.find_options_by_expiration(ticker, exp, optionType="put")
        expirations.append({
            "expiry": exp,
            "calls":  _rh_to_df(calls_raw),
            "puts":   _rh_to_df(puts_raw),
        })
        time.sleep(0.3)

    return {"expirations": expirations, "source": "robinhood"}


def _rh_to_df(raw: list) -> pd.DataFrame:
    records = []
    for opt in (raw or []):
        try:
            records.append({
                "contractSymbol":   opt.get("chain_symbol", ""),
                "strike":           float(opt.get("strike_price", 0) or 0),
                "volume":           int(opt.get("volume", 0) or 0),
                "openInterest":     int(opt.get("open_interest", 0) or 0),
                "impliedVolatility": float(opt.get("implied_volatility", 0) or 0),
                "lastPrice":        float(opt.get("last_trade_price", 0) or 0),
            })
        except Exception:
            continue
    return pd.DataFrame(records) if records else pd.DataFrame(
        columns=["contractSymbol", "strike", "volume", "openInterest",
                 "impliedVolatility", "lastPrice"]
    )


def _yf_options_chain(ticker: str, num_expirations: int) -> Optional[dict]:
    try:
        t    = yf.Ticker(ticker)
        dates = t.options
        if not dates:
            return None
        expirations = []
        for exp in dates[:num_expirations]:
            try:
                chain = t.option_chain(exp)
                expirations.append({
                    "expiry": exp,
                    "calls":  chain.calls,
                    "puts":   chain.puts,
                })
            except Exception:
                continue
        return {"expirations": expirations, "source": "yfinance"} if expirations else None
    except Exception:
        return None


# ── History ─────────────────────────────────────────────────────────────────────

def get_price_history(ticker: str, days: int = 30) -> Optional[pd.DataFrame]:
    try:
        t    = yf.Ticker(ticker)
        hist = t.history(period=f"{days}d")
        return hist if not hist.empty else None
    except Exception:
        return None


def get_ticker_info(ticker: str) -> dict:
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


def get_news(ticker: str) -> list:
    try:
        return yf.Ticker(ticker).news or []
    except Exception:
        return []
