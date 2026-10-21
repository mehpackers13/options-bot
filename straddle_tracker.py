"""
STRADDLE FORWARD TEST — paper only, no orders are ever placed
==============================================================
backtest.py showed that on days a stock trades >= 3x its 30-day average
volume, a 3%+ move follows within 5 trading days more often than usual.
That says nothing about PROFIT: options get pricier when everyone expects
a move. This tracker answers the money question going forward.

Every weekday evening (after the 4pm close) it:
  1. Finds the validated signal on finished daily bars: stock volume today
     >= 3x the trailing 30-day mean, across the same universe as backtest.py.
  2. Paper-buys an at-the-money straddle (1 call + 1 put, same strike) at
     closing quotes. Days at 2-3x go in a "near" group; a few random
     ordinary days per evening go in a "control" group.
  3. Five trading days later, prices the same two contracts again and
     records P&L three ways:
       pnl_mid   mid-to-mid (fair value; the headline number)
       pnl_cons  pay the asks in, hit the bids out, plus fees (worst case)
       pnl_floor exit valued at intrinsic |S - K| only (ignores time value
                 left, so a lower bound that needs no exit option quote)

The only question it has to answer: do spike-day straddles beat
control-day straddles, and is pnl_mid positive after enough samples?

Writes data/straddle_log.csv (every entry, exit and skip) and
data/straddle_summary.json. Run by .github/workflows/straddle.yml.

Usage:
  python straddle_tracker.py             # normal evening run
  python straddle_tracker.py --dry-run   # no file writes, no Discord
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import math
import os
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Optional

import pytz
import requests
import yfinance as yf

import config
from earnings_calendar import get_next_earnings

ET = pytz.timezone("America/New_York")
BASE = Path(__file__).parent
LOG_CSV = BASE / "data" / "straddle_log.csv"
SUMMARY_JSON = BASE / "data" / "straddle_summary.json"

# Same universe as backtest.UNIVERSE, minus MRO (delisted after the
# ConocoPhillips merger). Copied, not imported, so the two can't drift silently.
UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", "INTC", "AVGO",
    "QCOM", "NFLX", "ADBE", "CRM", "ORCL", "CSCO", "PYPL", "PEP", "KO", "WMT",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "AXP", "BRK-B",
    "XOM", "CVX", "COP", "SLB", "OXY",
    "JNJ", "UNH", "PFE", "ABBV", "MRK", "LLY", "GILD", "AMGN", "BMY",
    "GE", "F", "GM", "NKE", "MCD", "SBUX", "DIS", "HD", "LOW",
    "SPY", "QQQ", "IWM", "DIA", "XLE", "XLF", "XLK", "XLV", "XLY", "XLI", "XLU",
    "XLP", "XBI", "XRT", "GLD", "SLV", "USO", "TLT", "HYG", "LQD", "VXX", "UVXY",
]

SPIKE_MULT = 3.0          # the validated threshold (backtest.py VOLUME_SPIKE_MULT)
NEAR_MULT = 2.0           # 2-3x logged separately as a dose-response check
TRAILING_DAYS = 30
HOLD_DAYS = 5             # trading days, matches backtest MOVE_WINDOW_DAYS
MOVE_THRESHOLD = 0.03     # backtest "hit" = 3%+ max move inside the window
CONTROLS_PER_DAY = 3
EXPIRY_BUFFER_DAYS = 3    # expiry must be >= 3 calendar days after the exit
EXPIRY_MAX_DAYS = 21      # ...and no more than 21 after it
WIDE_SPREAD = 0.25        # (ask - bid) / mid above this is flagged "wide"
LAST_PRICE_MAX_AGE_H = 30 # lastPrice only counts if it traded this recently
FEE_PER_CONTRACT = 0.05   # $ per contract per side (regulatory fees; $0 commission)
EARLIEST_RUN_ET = (16, 15)  # closing quotes settle by ~16:15 ET

# NYSE full-day closures. Only used to PLAN the exit date for expiry
# selection; the actual exit is found by counting real daily bars.
NYSE_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31",
    "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
    "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19",
    "2028-07-04", "2028-09-04", "2028-11-23", "2028-12-25",
}

FIELDS = [
    "id", "group", "ticker", "status", "skip_reason",
    # entry
    "entry_date", "entry_ts", "vol_today", "vol_avg30", "vol_mult",
    "spot_entry", "expiry", "dte_entry", "strike", "call_symbol", "put_symbol",
    "call_bid_in", "call_ask_in", "call_last_in", "call_src_in",
    "put_bid_in", "put_ask_in", "put_last_in", "put_src_in",
    "entry_mid", "entry_ask", "implied_move_pct", "wide_in", "planned_exit",
    "earnings_date", "earnings_phase", "event_day",
    # exit
    "exit_date", "exit_ts", "exit_lag_days", "close_entry_final", "spot_exit",
    "call_bid_out", "call_ask_out", "call_last_out", "call_src_out",
    "put_bid_out", "put_ask_out", "put_last_out", "put_src_out", "wide_out",
    "exit_mid", "exit_bid", "intrinsic_exit",
    "pnl_mid", "pnl_cons", "pnl_floor",
    "realized_move_pct", "max_move_pct", "hit3", "vol_mult_final",
]


def log(msg: str) -> None:
    print(f"[{datetime.datetime.now(ET):%Y-%m-%d %H:%M:%S ET}] {msg}", flush=True)


# ── Calendar ──────────────────────────────────────────────────────────────────

def is_trading_day(d: datetime.date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in NYSE_HOLIDAYS


def add_trading_days(d: datetime.date, n: int) -> datetime.date:
    while n > 0:
        d += datetime.timedelta(days=1)
        if is_trading_day(d):
            n -= 1
    return d


def pick_expiry(expiries, planned_exit: datetime.date) -> Optional[str]:
    """First listed expiry at least EXPIRY_BUFFER_DAYS after the exit (so the
    straddle still has time value when we sell) and not absurdly far out."""
    lo = planned_exit + datetime.timedelta(days=EXPIRY_BUFFER_DAYS)
    hi = planned_exit + datetime.timedelta(days=EXPIRY_MAX_DAYS)
    for e in sorted(expiries):
        d = datetime.date.fromisoformat(e)
        if lo <= d <= hi:
            return e
    return None


# ── Quote handling ────────────────────────────────────────────────────────────

def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def price_leg(bid, ask, last, last_trade, now_utc: datetime.datetime):
    """Fair price for one option leg -> (price, source, wide) or (None, reason, False).
    Mid when the quote is two-sided and not crossed; otherwise a recent
    last trade; otherwise unpriceable."""
    bid, ask, last = _num(bid), _num(ask), _num(last)
    if bid is not None and ask is not None and bid > 0 and ask > 0 and bid <= ask:
        mid = (bid + ask) / 2
        return mid, "mid", (ask - bid) / mid > WIDE_SPREAD
    if last is not None and last > 0 and last_trade is not None:
        try:
            ts = last_trade.to_pydatetime() if hasattr(last_trade, "to_pydatetime") else last_trade
            if ts.tzinfo is None:
                ts = pytz.utc.localize(ts)
            if (now_utc - ts).total_seconds() <= LAST_PRICE_MAX_AGE_H * 3600:
                return last, "last", True
        except Exception:
            pass
    return None, "no_quote", False


def _row_quote(df, symbol: str):
    """Return (bid, ask, last, lastTradeDate) for a contract symbol, or None."""
    hit = df[df["contractSymbol"] == symbol]
    if hit.empty:
        return None
    r = hit.iloc[0]
    return r.get("bid"), r.get("ask"), r.get("lastPrice"), r.get("lastTradeDate")


def _info_quote(symbol: str):
    """Fallback for a single contract when it's missing from the chain."""
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        return None
    if not info:
        return None
    return info.get("bid"), info.get("ask"), info.get("regularMarketPrice"), None


def _r(x, nd=4):
    return "" if x is None else round(x, nd)


# ── Daily bars ────────────────────────────────────────────────────────────────

def fetch_daily(tickers, period: str = "6mo") -> dict:
    """{ticker: DataFrame of daily bars, index = datetime.date}. Today's bar,
    if present in the evening, has a real (possibly not-yet-final) Volume
    and a NaN Close."""
    df = yf.download(tickers, period=period, interval="1d", auto_adjust=False,
                     group_by="ticker", progress=False, threads=True)
    out = {}
    for t in tickers:
        try:
            sub = df[t] if len(tickers) > 1 else df
            sub = sub.dropna(subset=["Volume"])
        except Exception:
            continue
        if sub.empty:
            continue
        sub = sub.copy()
        sub.index = [ts.date() for ts in sub.index]
        out[t] = sub
    return out


def volume_mult(bars, day: datetime.date):
    """(vol_day, trailing_mean, mult) for `day` vs the 30 bars before it."""
    days = list(bars.index)
    if day not in days:
        return None
    i = days.index(day)
    if i < TRAILING_DAYS:
        return None
    vols = [float(v) for v in bars["Volume"].iloc[i - TRAILING_DAYS:i]]
    avg = sum(vols) / TRAILING_DAYS
    v = float(bars["Volume"].iloc[i])
    if avg <= 0:
        return None
    return v, avg, v / avg


# ── Storage ───────────────────────────────────────────────────────────────────

def load_rows() -> list:
    if not LOG_CSV.exists():
        return []
    with open(LOG_CSV, newline="") as f:
        return list(csv.DictReader(f))


def save_rows(rows: list) -> None:
    LOG_CSV.parent.mkdir(exist_ok=True)
    tmp = LOG_CSV.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    os.replace(tmp, LOG_CSV)


# ── Entry ─────────────────────────────────────────────────────────────────────

def _reaction_days(ts) -> set:
    """The session(s) that trade on an earnings report: the report day if it
    came before the open, the next session if after the close, both if the
    time is unknown (Yahoo gives midnight)."""
    d = ts.date()
    nxt = add_trading_days(d, 1)
    if ts.hour == 0 and ts.minute == 0:
        return {d, nxt}
    return {d} if ts.hour < 12 else {nxt}


def earnings_phase(ticker: str, today: datetime.date, planned_exit: datetime.date):
    """Where earnings sit relative to this trade. Volume spikes are often the
    market reacting to a report, and post-report straddles behave nothing
    like pre-report ones, so results are split on this.
      reaction_day  today's session is the reaction to a report
      in_window     a report's reaction session falls inside the hold
      recent        reacted within the 5 sessions before entry
      none / unknown"""
    try:
        ed = yf.Ticker(ticker).get_earnings_dates(limit=8)
        stamps = [ts.tz_convert(ET) if ts.tzinfo else ET.localize(ts) for ts in ed.index]
    except Exception:
        stamps = []
    if not stamps:
        # Fallback: date only, no report time. The calendar also rolls to the
        # next quarter soon after a report, so this can miss reaction days.
        d = get_next_earnings(ticker)
        if d is None:
            return "", "unknown"
        if d == today:
            return d.isoformat(), "reaction_day"
        if today < d <= planned_exit:
            return d.isoformat(), "in_window"
        return d.isoformat(), "none"
    recent_start = today
    for _ in range(HOLD_DAYS):
        recent_start -= datetime.timedelta(days=1)
        while not is_trading_day(recent_start):
            recent_start -= datetime.timedelta(days=1)
    best = None
    for ts in sorted(stamps):
        days = _reaction_days(ts)
        if today in days:
            return ts.isoformat(), "reaction_day"
        if any(today < d <= planned_exit for d in days):
            best = best or (ts.isoformat(), "in_window")
        elif any(recent_start <= d < today for d in days):
            best = best or (ts.isoformat(), "recent")
    return best or ("", "none")


def event_day(d: datetime.date) -> str:
    """Days when volume spikes for mechanical reasons, not news: quarterly
    options expiry + S&P rebalance (3rd Friday of Mar/Jun/Sep/Dec), the
    Russell reconstitution (last Friday of June), and monthly expiry."""
    if d.weekday() != 4:
        return ""
    if d.month == 6 and (d + datetime.timedelta(days=7)).month == 7:
        return "russell_recon"
    if 15 <= d.day <= 21:
        return "quad_witching" if d.month in (3, 6, 9, 12) else "monthly_opex"
    return ""


def open_straddle(ticker: str, group: str, today: datetime.date, vm,
                  now_utc: datetime.datetime) -> dict:
    vol, avg, mult = vm
    planned_exit = add_trading_days(today, HOLD_DAYS)
    row = {
        "id": f"{today.isoformat()}:{ticker}", "group": group, "ticker": ticker,
        "entry_date": today.isoformat(), "entry_ts": now_utc.isoformat(timespec="seconds"),
        "vol_today": int(vol), "vol_avg30": int(avg), "vol_mult": round(mult, 3),
        "planned_exit": planned_exit.isoformat(),
    }
    row["earnings_date"], row["earnings_phase"] = earnings_phase(ticker, today, planned_exit)
    row["event_day"] = event_day(today)

    def skip(reason):
        row.update(status="skipped", skip_reason=reason)
        return row

    try:
        tk = yf.Ticker(ticker)
        expiry = pick_expiry(tk.options or (), planned_exit)
        if not expiry:
            return skip("no_expiry")
        ch = tk.option_chain(expiry)
    except Exception as e:
        return skip(f"chain_error:{type(e).__name__}")

    und = ch.underlying if isinstance(ch.underlying, dict) else {}
    spot = _num(und.get("regularMarketPrice"))
    mkt_time = und.get("regularMarketTime")
    if spot is None or spot <= 0:
        return skip("no_spot")
    if mkt_time:
        quote_day = datetime.datetime.fromtimestamp(int(mkt_time), ET).date()
        if quote_day != today:
            return skip(f"stale_spot:{quote_day}")

    calls, puts = ch.calls, ch.puts
    strikes = sorted(set(calls["strike"]).intersection(set(puts["strike"])))
    if not strikes:
        return skip("no_common_strike")
    k = min(strikes, key=lambda s: (abs(s - spot), s))
    c = calls[calls["strike"] == k].iloc[0]
    p = puts[puts["strike"] == k].iloc[0]

    cp, csrc, cwide = price_leg(c["bid"], c["ask"], c["lastPrice"], c["lastTradeDate"], now_utc)
    pp, psrc, pwide = price_leg(p["bid"], p["ask"], p["lastPrice"], p["lastTradeDate"], now_utc)
    row.update({
        "spot_entry": round(spot, 4), "expiry": expiry,
        "dte_entry": (datetime.date.fromisoformat(expiry) - today).days,
        "strike": k, "call_symbol": c["contractSymbol"], "put_symbol": p["contractSymbol"],
        "call_bid_in": _r(_num(c["bid"])), "call_ask_in": _r(_num(c["ask"])),
        "call_last_in": _r(_num(c["lastPrice"])), "call_src_in": csrc,
        "put_bid_in": _r(_num(p["bid"])), "put_ask_in": _r(_num(p["ask"])),
        "put_last_in": _r(_num(p["lastPrice"])), "put_src_in": psrc,
    })
    if cp is None or pp is None:
        return skip("leg_unpriced")

    entry_mid = cp + pp
    ca, pa = _num(c["ask"]), _num(p["ask"])
    entry_ask = ca + pa if (ca and pa and ca > 0 and pa > 0) else None
    row.update({
        "status": "open", "entry_mid": round(entry_mid, 4), "entry_ask": _r(entry_ask),
        "implied_move_pct": round(entry_mid / spot * 100, 3),
        "wide_in": int(bool(cwide or pwide)),
    })
    return row


# ── Exit ──────────────────────────────────────────────────────────────────────

def close_straddle(row: dict, bars, today: datetime.date,
                   now_utc: datetime.datetime) -> bool:
    """Price the exit once HOLD_DAYS real trading bars have printed after
    the entry. Returns True if the row was closed."""
    entry = datetime.date.fromisoformat(row["entry_date"])
    after = [d for d in bars.index if d > entry]
    if len(after) < HOLD_DAYS:
        return False
    exit_day = after[HOLD_DAYS - 1]
    lag = len(after) - HOLD_DAYS          # bars printed past the planned exit
    on_time = (exit_day == today and lag == 0)

    # Finalized closes for the path; the exit day's own close is NaN in the
    # evening, so take it from the live quote when we're pricing on time.
    closes = [_num(bars.loc[d, "Close"]) for d in after[:HOLD_DAYS]]
    close_entry = _num(bars.loc[entry, "Close"]) if entry in bars.index else None
    spot_exit = closes[-1]

    tk = yf.Ticker(row["ticker"])
    chain = None
    try:
        if row["expiry"] in (tk.options or ()):
            chain = tk.option_chain(row["expiry"])
    except Exception:
        chain = None
    if on_time and chain is not None:
        und = chain.underlying if isinstance(chain.underlying, dict) else {}
        live = _num(und.get("regularMarketPrice"))
        if live and live > 0:
            spot_exit = live
    if spot_exit is None or close_entry is None:
        return False                      # try again next evening
    closes[-1] = spot_exit

    def quote(symbol, side_df):
        q = _row_quote(side_df, symbol) if side_df is not None else None
        return q or _info_quote(symbol)

    cq = quote(row["call_symbol"], chain.calls if chain is not None else None)
    pq = quote(row["put_symbol"], chain.puts if chain is not None else None)

    k = float(row["strike"])
    entry_mid = float(row["entry_mid"])
    intrinsic = abs(spot_exit - k)
    path = [abs(c - close_entry) / close_entry for c in closes if c is not None]
    vmf = volume_mult(bars, entry)

    row.update({
        "status": "closed", "exit_date": exit_day.isoformat(),
        "exit_ts": now_utc.isoformat(timespec="seconds"), "exit_lag_days": lag,
        "close_entry_final": round(close_entry, 4), "spot_exit": round(spot_exit, 4),
        "intrinsic_exit": round(intrinsic, 4),
        "pnl_floor": round((intrinsic - entry_mid) / entry_mid, 4),
        "realized_move_pct": round((spot_exit - close_entry) / close_entry * 100, 3),
        "max_move_pct": round(max(path) * 100, 3) if path else "",
        "hit3": int(bool(path) and max(path) >= MOVE_THRESHOLD),
        "vol_mult_final": round(vmf[2], 3) if vmf else "",
    })

    # Option marks only mean something on the evening of the exit day.
    if not on_time or cq is None or pq is None:
        return True
    cp, csrc, cwide = price_leg(cq[0], cq[1], cq[2], cq[3], now_utc)
    pp, psrc, pwide = price_leg(pq[0], pq[1], pq[2], pq[3], now_utc)
    row.update({
        "call_bid_out": _r(_num(cq[0])), "call_ask_out": _r(_num(cq[1])),
        "call_last_out": _r(_num(cq[2])), "call_src_out": csrc,
        "put_bid_out": _r(_num(pq[0])), "put_ask_out": _r(_num(pq[1])),
        "put_last_out": _r(_num(pq[2])), "put_src_out": psrc,
        "wide_out": int(bool(cwide or pwide)),
    })
    if cp is not None and pp is not None:
        exit_mid = cp + pp
        row["exit_mid"] = round(exit_mid, 4)
        row["pnl_mid"] = round((exit_mid - entry_mid) / entry_mid, 4)
    cb, pb = _num(cq[0]), _num(pq[0])
    if row.get("entry_ask") not in ("", None) and cb is not None and pb is not None:
        entry_ask = float(row["entry_ask"])
        exit_bid = max(cb, 0.0) + max(pb, 0.0)
        fees = 4 * FEE_PER_CONTRACT / 100     # 2 legs x in/out, per share
        row["exit_bid"] = round(exit_bid, 4)
        row["pnl_cons"] = round((exit_bid - entry_ask - fees) / entry_ask, 4)
    return True


# ── Summary ───────────────────────────────────────────────────────────────────

def _stats(pairs: list) -> dict:
    """pairs = [(entry_date, value)]. The confidence interval is built from
    per-DATE averages: spikes cluster (16 tickers on one expiry Friday), and
    treating each as independent would overstate certainty."""
    xs = [v for _, v in pairs]
    n = len(xs)
    if n == 0:
        return {"n": 0, "dates": 0}
    by_date = {}
    for d, v in pairs:
        by_date.setdefault(d, []).append(v)
    dm = [sum(v) / len(v) for v in by_date.values()]
    mean = sum(xs) / n
    out = {"n": n, "dates": len(dm), "mean": round(mean, 4),
           "median": round(statistics.median(xs), 4),
           "win_rate": round(sum(1 for x in xs if x > 0) / n, 3)}
    if len(dm) >= 3:
        m = sum(dm) / len(dm)
        se = statistics.stdev(dm) / math.sqrt(len(dm))
        out.update(date_mean=round(m, 4), ci95=[round(m - 1.96 * se, 4), round(m + 1.96 * se, 4)],
                   t=round(m / se, 2) if se > 0 else None)
    return out


def _clean(r: dict) -> bool:
    """Both legs priced off a real two-sided, not-wide quote at entry AND exit."""
    return (r.get("call_src_in") == r.get("put_src_in") == "mid"
            and r.get("call_src_out") == r.get("put_src_out") == "mid"
            and str(r.get("wide_in")) == "0" and str(r.get("wide_out")) == "0")


def summarize(rows: list) -> dict:
    def f(r, k):
        v = r.get(k, "")
        return None if v in ("", None) else float(v)

    def st(rs, k):
        return _stats([(r["entry_date"], f(r, k)) for r in rs if f(r, k) is not None])

    groups = {}
    for g in ("spike", "near", "control"):
        closed = [r for r in rows if r.get("group") == g and r.get("status") == "closed"]
        on_time = [r for r in closed if r.get("exit_lag_days") in ("0", 0)]
        groups[g] = {
            "open": sum(1 for r in rows if r.get("group") == g and r.get("status") == "open"),
            "closed": len(closed),
            "skipped": sum(1 for r in rows if r.get("group") == g and r.get("status") == "skipped"),
            "late_exits": len(closed) - len(on_time),
            "pnl_mid": st(on_time, "pnl_mid"),
            "pnl_mid_clean_quotes": st([r for r in on_time if _clean(r)], "pnl_mid"),
            "pnl_mid_no_event_day": st([r for r in on_time if not r.get("event_day")], "pnl_mid"),
            "pnl_cons": st(on_time, "pnl_cons"),
            "pnl_floor": st(closed, "pnl_floor"),
            "hit3_rate": st(closed, "hit3").get("mean"),
            "avg_implied_move_pct": st(closed, "implied_move_pct").get("mean"),
            "pnl_mid_by_earnings": {
                ph: st([r for r in on_time if r.get("earnings_phase") == ph], "pnl_mid")
                for ph in ("reaction_day", "in_window", "recent", "none", "unknown")
            },
        }
    skips = {}
    for r in rows:
        if r.get("status") == "skipped":
            reason = (r.get("skip_reason") or "").split(":")[0]
            skips[reason] = skips.get(reason, 0) + 1
    return {
        "updated": datetime.datetime.now(ET).isoformat(timespec="seconds"),
        "paper_only": True,
        "question": "Do straddles bought on >=3x stock-volume days make money, and beat random days?",
        "groups": groups, "skip_reasons": skips,
        "verdict_rule": ("Needs >=30 scored spike trades on >=20 different days, a date-clustered "
                         "ci95 above 0, and a spike mean above the control mean."),
    }


def _verdict(s: dict) -> str:
    sp = s["groups"]["spike"]["pnl_mid"]
    ct = s["groups"]["control"]["pnl_mid"]
    if sp.get("n", 0) < 30 or sp.get("dates", 0) < 20:
        return (f"Collecting data ({sp.get('n', 0)}/30 spike trades scored, "
                f"{sp.get('dates', 0)}/20 different days).")
    lo = sp["ci95"][0]
    if lo > 0 and sp["mean"] > ct.get("mean", -1):
        return "Spike straddles show a real profit so far."
    if sp["ci95"][1] < 0:
        return "Spike straddles are losing money — signal does not pay."
    return "No clear answer yet — results are within noise."


# ── Discord ───────────────────────────────────────────────────────────────────

def post_discord(opened: list, closed: list, summary: dict, weekly: bool) -> None:
    webhook = getattr(config, "DISCORD_WEBHOOK_URL", "")
    if not webhook:
        return
    lines = []
    for r in opened:
        if r.get("group") == "spike" and r.get("status") == "open":
            lines.append(f"📝 **{r['ticker']}** volume {float(r['vol_mult']):.1f}x avg — paper straddle "
                         f"${float(r['entry_mid']):.2f} (market expects ±{float(r['implied_move_pct']):.1f}%), "
                         f"strike {r['strike']}, exp {r['expiry']}"
                         + (" — earnings day" if r.get("earnings_phase") == "entry_day" else ""))
    for r in closed:
        if r.get("group") == "spike" and r.get("pnl_mid") not in ("", None):
            lines.append(f"✅ **{r['ticker']}** paper straddle closed: {float(r['pnl_mid'])*100:+.0f}% "
                         f"(stock moved {float(r['realized_move_pct']):+.1f}%)")
    if weekly:
        g = summary["groups"]
        def fmt(k):
            st = g[k]["pnl_mid"]
            return f"{st['mean']*100:+.0f}% avg over {st['n']}" if st.get("n") else "no results yet"
        lines.append(f"📊 Weekly straddle test — spike days: {fmt('spike')} | near: {fmt('near')} | "
                     f"random days: {fmt('control')}. {_verdict(summary)}")
    if not lines:
        return
    content = "**Options volume-spike forward test (PAPER — no money)**\n" + "\n".join(lines)
    try:
        requests.post(webhook, json={"content": content[:1900]}, timeout=10)
    except Exception as e:
        log(f"Discord post failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, now_et: Optional[datetime.datetime] = None) -> int:
    now_et = now_et or datetime.datetime.now(ET)
    now_utc = now_et.astimezone(pytz.utc)
    today = now_et.date()
    if (now_et.hour, now_et.minute) < EARLIEST_RUN_ET:
        log(f"Too early ({now_et:%H:%M} ET) — closing quotes not final. Nothing done.")
        return 0
    if not is_trading_day(today):
        log("Not a trading day (weekend/holiday). Nothing done.")
        return 0

    rows = load_rows()
    seen = {r["id"] for r in rows}
    bars = fetch_daily(UNIVERSE)
    spy = bars.get("SPY")
    if spy is None or spy.index[-1] != today:
        log("SPY has no bar for today — market closed or data late. Nothing done.")
        return 0

    # 1) Exits first, so a re-run never double-processes anything.
    closed = []
    for r in rows:
        if r.get("status") != "open":
            continue
        b = bars.get(r["ticker"])
        if b is None:
            continue
        try:
            if close_straddle(r, b, today, now_utc):
                closed.append(r)
                log(f"Closed {r['id']} ({r['group']}): pnl_mid={r.get('pnl_mid', '')} "
                    f"floor={r.get('pnl_floor')} lag={r.get('exit_lag_days')}")
        except Exception as e:
            log(f"Exit failed for {r['id']}: {type(e).__name__}: {e}")
        time.sleep(0.3)

    # 2) Today's signal on finished bars.
    spikes, near, ordinary, missing = [], [], [], []
    for t in UNIVERSE:
        b = bars.get(t)
        if b is None or b.index[-1] != today:
            missing.append(t)
            continue
        vm = volume_mult(b, today)
        if vm is None:
            missing.append(t)
            continue
        if vm[2] >= SPIKE_MULT:
            spikes.append((t, vm))
        elif vm[2] >= NEAR_MULT:
            near.append((t, vm))
        else:
            ordinary.append((t, vm))
    # Reproducible control picks, topped up only to CONTROLS_PER_DAY: a later
    # cron the same evening can see slightly different volumes, and must not
    # add a second batch of controls.
    have = sum(1 for r in rows if r.get("group") == "control" and r.get("entry_date") == today.isoformat())
    rng = random.Random(today.isoformat())
    pool = [o for o in ordinary if f"{today.isoformat()}:{o[0]}" not in seen]
    controls = rng.sample(pool, max(0, min(CONTROLS_PER_DAY - have, len(pool))))
    log(f"Signal scan: {len(spikes)} spike(s) >= {SPIKE_MULT}x, {len(near)} near, "
        f"{len(ordinary)} ordinary, {len(missing)} without a usable bar"
        + (f" ({', '.join(missing)})" if missing else ""))

    opened = []
    for group, picks in (("spike", spikes), ("near", near), ("control", controls)):
        for t, vm in picks:
            if f"{today.isoformat()}:{t}" in seen:
                continue
            r = open_straddle(t, group, today, vm, now_utc)
            rows.append(r)
            opened.append(r)
            log(f"{'Opened' if r['status'] == 'open' else 'Skipped'} {r['id']} ({group}, "
                f"{vm[2]:.2f}x) {r.get('skip_reason') or ''}"
                + (f" straddle ${r['entry_mid']} = ±{r['implied_move_pct']}%" if r['status'] == 'open' else "")
                + f" earnings={r.get('earnings_phase')}")
            time.sleep(0.3)

    summary = summarize(rows)
    log("Summary: " + json.dumps(summary["groups"]["spike"]["pnl_mid"]) + " | " + _verdict(summary))
    if dry_run:
        log(f"Dry run — would write {len(rows)} rows ({len(opened)} new, {len(closed)} closed).")
        return 0
    # Weekly digest once per Friday, not once per cron.
    prev = {}
    try:
        prev = json.loads(SUMMARY_JSON.read_text()) if SUMMARY_JSON.exists() else {}
    except Exception:
        pass
    weekly = today.weekday() == 4 and prev.get("weekly_posted") != today.isoformat()
    summary["weekly_posted"] = today.isoformat() if weekly else prev.get("weekly_posted", "")
    save_rows(rows)
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2))
    post_discord(opened, closed, summary, weekly=weekly)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--dry-run", action="store_true", help="no file writes, no Discord")
    sys.exit(run(dry_run=ap.parse_args().dry_run))
