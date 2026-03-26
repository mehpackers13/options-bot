"""
DATA SOURCES
============
Priority order:
  1. Tradier API  — real-time options data, simple Bearer token, no MFA
  2. yfinance     — 15-min delayed fallback, always works, no auth needed

Robinhood (robin_stocks) has been removed: Robinhood eliminated authenticator-app
2FA in December 2024 and now requires mobile-app device approval on every new
login location. GitHub Actions is a new location on every run — no programmatic
workaround exists.

HOW TO ENABLE TRADIER (takes ~5 minutes, completely free):
  1. Sign up at tradier.com → open a free brokerage account (no deposit needed)
  2. Go to tradier.com/profile#api → copy your API Access Token
  3. In GitHub → repo Settings → Secrets → add:
       TRADIER_API_TOKEN = <your token>
  That's it. Real-time options data, no MFA, token never expires.

Without TRADIER_API_TOKEN set, the bot uses yfinance (15-min delayed) — still
fully functional for detecting unusual volume, IV spikes, and P/C skews.
"""

import os
import time
from typing import Optional

import pandas as pd
import requests
import yfinance as yf

# ── State ───────────────────────────────────────────────────────────────────────

_tradier_token: str = ""
_tradier_base:  str = "https://api.tradier.com/v1"
_source_label:  str = "yfinance"   # updated in init()

_TRADIER_HEADERS = lambda token: {   # noqa: E731
    "Authorization": f"Bearer {token}",
    "Accept":        "application/json",
}


# ── Initialisation ──────────────────────────────────────────────────────────────

def init() -> None:
    """
    Call once at startup. Checks for TRADIER_API_TOKEN and validates it.
    Falls back silently to yfinance if token is absent or invalid.
    """
    global _tradier_token, _source_label

    token = os.environ.get("TRADIER_API_TOKEN", "").strip()
    if not token:
        print("[data_sources] No TRADIER_API_TOKEN — using yfinance (15-min delayed)")
        _source_label = "yfinance"
        return

    # Quick validation: hit the /user/profile endpoint
    try:
        resp = requests.get(
            f"{_tradier_base}/user/profile",
            headers=_TRADIER_HEADERS(token),
            timeout=8,
        )
        if resp.status_code == 200:
            profile = resp.json().get("profile", {})
            name    = profile.get("name", "unknown")
            _tradier_token = token
            _source_label  = "tradier"
            print(f"[data_sources] Tradier connected — account: {name} ✅  (real-time data)")
        else:
            print(
                f"[data_sources] Tradier token invalid (HTTP {resp.status_code}) "
                f"— using yfinance"
            )
            _source_label = "yfinance"
    except Exception as exc:
        print(f"[data_sources] Tradier connection failed ({exc}) — using yfinance")
        _source_label = "yfinance"


def get_source() -> str:
    return _source_label


# ── Current price ───────────────────────────────────────────────────────────────

def get_current_price(ticker: str) -> Optional[float]:
    if _tradier_token:
        try:
            resp = requests.get(
                f"{_tradier_base}/markets/quotes",
                headers=_TRADIER_HEADERS(_tradier_token),
                params={"symbols": ticker, "greeks": "false"},
                timeout=8,
            )
            if resp.status_code == 200:
                q = resp.json().get("quotes", {}).get("quote", {})
                last = q.get("last") or q.get("close") or q.get("prevclose")
                if last and float(last) > 0:
                    return float(last)
        except Exception:
            pass

    # yfinance fallback
    try:
        t     = yf.Ticker(ticker)
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
    Returns:
      {
        "expirations": [{"expiry": str, "calls": DataFrame, "puts": DataFrame}, ...],
        "source": "tradier" | "yfinance"
      }
    Returns None on complete failure.
    """
    if _tradier_token:
        result = _tradier_options_chain(ticker, num_expirations)
        if result:
            return result
        print(f"[data_sources] Tradier chain failed for {ticker} — falling back to yfinance")

    return _yf_options_chain(ticker, num_expirations)


# ── Tradier implementation ──────────────────────────────────────────────────────

def _tradier_get_expirations(ticker: str) -> list:
    """Return list of expiration date strings from Tradier."""
    try:
        resp = requests.get(
            f"{_tradier_base}/markets/options/expirations",
            headers=_TRADIER_HEADERS(_tradier_token),
            params={"symbol": ticker, "includeAllRoots": "true", "strikes": "false"},
            timeout=8,
        )
        if resp.status_code != 200:
            return []
        dates = resp.json().get("expirations", {}).get("date", [])
        if isinstance(dates, str):
            dates = [dates]
        return dates or []
    except Exception:
        return []


def _tradier_options_chain(ticker: str, num_expirations: int) -> Optional[dict]:
    """Fetch options chain from Tradier for the nearest N expirations."""
    expirations_dates = _tradier_get_expirations(ticker)
    if not expirations_dates:
        return None

    expirations = []
    for exp in expirations_dates[:num_expirations]:
        try:
            resp = requests.get(
                f"{_tradier_base}/markets/options/chains",
                headers=_TRADIER_HEADERS(_tradier_token),
                params={"symbol": ticker, "expiration": exp, "greeks": "true"},
                timeout=10,
            )
            if resp.status_code != 200:
                continue

            raw_options = resp.json().get("options", {})
            if not raw_options:
                continue
            opts = raw_options.get("option", [])
            if isinstance(opts, dict):
                opts = [opts]   # single-contract edge case

            calls_rows, puts_rows = [], []
            for opt in opts:
                # Tradier IV is already a decimal fraction (0.25 = 25%)
                greeks   = opt.get("greeks") or {}
                iv_raw   = greeks.get("mid_iv") or greeks.get("bid_iv") or opt.get("iv", 0) or 0
                row = {
                    "contractSymbol":    opt.get("symbol", ""),
                    "strike":            float(opt.get("strike", 0)),
                    "volume":            int(opt.get("volume", 0) or 0),
                    "openInterest":      int(opt.get("open_interest", 0) or 0),
                    "impliedVolatility": float(iv_raw),
                    "lastPrice":         float(opt.get("last", 0) or 0),
                }
                if opt.get("option_type") == "call":
                    calls_rows.append(row)
                else:
                    puts_rows.append(row)

            expirations.append({
                "expiry": exp,
                "calls":  pd.DataFrame(calls_rows) if calls_rows else _empty_df(),
                "puts":   pd.DataFrame(puts_rows)  if puts_rows  else _empty_df(),
            })
            time.sleep(0.2)   # polite rate limiting

        except Exception as exc:
            print(f"[data_sources] Tradier chain error {ticker} {exp}: {exc}")
            continue

    return {"expirations": expirations, "source": "tradier"} if expirations else None


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["contractSymbol", "strike", "volume",
                 "openInterest", "impliedVolatility", "lastPrice"]
    )


# ── yfinance implementation ─────────────────────────────────────────────────────

def _yf_options_chain(ticker: str, num_expirations: int) -> Optional[dict]:
    try:
        t     = yf.Ticker(ticker)
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


# ── Utility helpers ─────────────────────────────────────────────────────────────

def get_price_history(ticker: str, days: int = 30) -> Optional[pd.DataFrame]:
    try:
        hist = yf.Ticker(ticker).history(period=f"{days}d")
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
