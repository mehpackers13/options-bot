"""
STRADDLE BACKTEST — would buying a straddle on volume-spike days have paid?
===========================================================================
backtest.py proved spike days MOVE more. This asks whether they move more
than the options market already charges for. Historical option prices
aren't free, so each straddle is priced with Black-Scholes using CBOE's
published implied-volatility index for that underlying (VIX9D for SPY,
VXN for QQQ, VXAPL for AAPL, ...): the market's own vol price that day.

Trade (same as straddle_tracker.py, the live paper test):
  entry  close of a day whose stock volume >= 3x the trailing 30-day mean
  option ATM straddle, first Friday expiry >= 3 calendar days after exit
  exit   close 5 trading days later, re-priced with that day's vol index
Groups: spike (>=3x), near (2-3x), control (every day < 2x, same tickers).

Known model limits (read before trusting the numbers):
  - Vol indices are ~30-day variance-swap rates (VIX9D is 9-day). Real
    1-3 week ATM options can be cheaper (skew) or pricier (event premium
    before earnings). `--calibrate` compares the model with live chains.
  - Earnings inside the hold window is where a 30-day index is most wrong,
    so those trades are reported separately.
  - Costs: a per-underlying half-spread (fraction of premium) is charged
    on entry and exit for the *_cost numbers.

Outputs (never touches backtest.py's files):
  data/straddle_backtest_results.json
  data/straddle_backtest_trades.csv   (spike + near trades)

Usage:
  python straddle_backtest.py              # full backtest, 2011-today
  python straddle_backtest.py --calibrate  # model vs today's real chains (run after the close)
"""
from __future__ import annotations

import argparse
import csv
import datetime
import io
import json
import math
import statistics
import time
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Optional

import requests
import yfinance as yf

BASE = Path(__file__).parent
RESULTS = BASE / "data" / "straddle_backtest_results.json"
TRADES = BASE / "data" / "straddle_backtest_trades.csv"

CBOE_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv"

# underlying -> CBOE implied-vol index. "SPY30" is SPY priced off the
# 30-day VIX instead of 9-day VIX9D, to measure the term-structure error.
IV_INDEX = {
    "SPY": "VIX9D", "SPY30": "VIX", "QQQ": "VXN", "DIA": "VXD", "IWM": "RVX",
    "GLD": "GVZ", "USO": "OVX", "SLV": "VXSLV", "TLT": "VXTLT",
    "EEM": "VXEEM", "FXI": "VXFXI", "EWZ": "VXEWZ", "GDX": "VXGDX",
    "AAPL": "VXAPL", "AMZN": "VXAZN", "GOOG": "VXGOG", "GS": "VXGS", "IBM": "VXIBM",
}
STOCKS = {"AAPL", "AMZN", "GOOG", "GS", "IBM"}   # have earnings; ETFs don't

SPIKE_MULT = 3.0
NEAR_MULT = 2.0
TRAILING_DAYS = 30
HOLD_DAYS = 5
EXPIRY_BUFFER_DAYS = 3
START = "2010-09-01"            # 30+ bars of volume before the vol indices begin
DEFAULT_HALF_SPREAD = 0.03      # used when --calibrate hasn't measured one
CALIBRATION = BASE / "data" / "straddle_calibration.json"


# ── Math ──────────────────────────────────────────────────────────────────────

def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def straddle_value(s: float, k: float, t_years: float, vol: float) -> float:
    """Black-Scholes call + put, zero rates/dividends (2-week ATM: negligible)."""
    if t_years <= 0 or vol <= 0:
        return abs(s - k)
    sq = vol * math.sqrt(t_years)
    d1 = (math.log(s / k) + 0.5 * sq * sq) / sq
    d2 = d1 - sq
    call = s * _ncdf(d1) - k * _ncdf(d2)
    put = k * _ncdf(-d2) - s * _ncdf(-d1)
    return call + put


def first_friday_on_or_after(d: datetime.date) -> datetime.date:
    return d + datetime.timedelta(days=(4 - d.weekday()) % 7)


# ── Data ──────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=None)
def load_iv(index: str) -> dict:
    """{date: vol as a decimal} from CBOE's history CSV."""
    r = requests.get(CBOE_URL.format(index), timeout=30)
    r.raise_for_status()
    out = {}
    rows = csv.reader(io.StringIO(r.text))
    header = [h.strip().upper() for h in next(rows)]
    col = header.index("CLOSE") if "CLOSE" in header else len(header) - 1
    for row in rows:
        try:
            d = datetime.datetime.strptime(row[0].strip(), "%m/%d/%Y").date()
            v = float(row[col])
        except (ValueError, IndexError):
            continue
        if 1.0 < v < 1000.0:            # OVX printed 325 in April 2020 — keep it
            out[d] = v / 100.0
    return out


@lru_cache(maxsize=None)
def load_bars(ticker: str) -> list:
    """[(date, close, volume)] split-adjusted daily bars, finished days only."""
    h = yf.Ticker(ticker).history(start=START, interval="1d", auto_adjust=False)
    out = []
    for ts, row in h.iterrows():
        c, v = row["Close"], row["Volume"]
        if c != c or v != v or c <= 0:          # NaN (e.g. today's unfinished bar)
            continue
        out.append((ts.date(), float(c), float(v)))
    return out


@lru_cache(maxsize=None)
def load_dividends(ticker: str) -> dict:
    """{ex_date: cash per share}. Options are priced off the forward, so a
    known dividend drop is not a 'move' the straddle gets paid for."""
    try:
        return {ts.date(): float(v) for ts, v in yf.Ticker(ticker).dividends.items()}
    except Exception:
        return {}


def event_day(d: datetime.date) -> str:
    """Same tags as straddle_tracker.event_day: mechanical-volume days."""
    if d.weekday() != 4:
        return ""
    if d.month == 6 and (d + datetime.timedelta(days=7)).month == 7:
        return "russell_recon"
    if 15 <= d.day <= 21:
        return "quad_witching" if d.month in (3, 6, 9, 12) else "monthly_opex"
    return ""


@lru_cache(maxsize=None)
def load_earnings(ticker: str) -> set:
    try:
        ed = yf.Ticker(ticker).get_earnings_dates(limit=100)
        return {ts.date() for ts in ed.index}
    except Exception:
        return set()


# ── Backtest ──────────────────────────────────────────────────────────────────

def run_underlying(name: str, half_spread: float, vol_scale: float = 1.0) -> tuple:
    """Every eligible day for one underlying -> (trades, skipped_count)."""
    ticker = "SPY" if name == "SPY30" else name
    iv = load_iv(IV_INDEX[name])
    bars = load_bars(ticker)
    earn = load_earnings(ticker) if ticker in STOCKS else set()
    divs = load_dividends(ticker)
    trades, skipped = [], 0
    for i in range(TRAILING_DAYS, len(bars) - HOLD_DAYS):
        d0, s0, v0 = bars[i]
        window_vols = [b[2] for b in bars[i - TRAILING_DAYS:i]]
        trailing = sum(window_vols) / TRAILING_DAYS
        if trailing <= 0:
            continue
        # Near-zero volume prints (e.g. GOOG's April 2014 share-class split)
        # would fake a spike against a deflated average.
        if min(window_vols) < 0.05 * statistics.median(window_vols) or v0 <= 0:
            skipped += 1
            continue
        mult = v0 / trailing
        group = "spike" if mult >= SPIKE_MULT else "near" if mult >= NEAR_MULT else "control"
        d5, s5, _ = bars[i + HOLD_DAYS]
        # Add back dividends that went ex during the hold (see load_dividends).
        s5 += sum(v for d, v in divs.items() if d0 < d <= d5)
        if d0 not in iv or d5 not in iv:
            skipped += 1
            continue
        expiry = first_friday_on_or_after(d5 + datetime.timedelta(days=EXPIRY_BUFFER_DAYS))
        t0 = (expiry - d0).days / 365.0
        t5 = (expiry - d5).days / 365.0
        k = s0
        p0 = straddle_value(s0, k, t0, iv[d0])
        p5 = straddle_value(s5, k, t5, iv[d5])
        pnl = (p5 - p0) / p0
        pnl_cost = (p5 * (1 - half_spread) - p0 * (1 + half_spread)) / (p0 * (1 + half_spread))
        # Same trade with vol rescaled so the model matches real chain prices
        # (vol indices are variance-swap rates, a bit above ATM implied vol).
        c0 = straddle_value(s0, k, t0, iv[d0] * vol_scale)
        c5 = straddle_value(s5, k, t5, iv[d5] * vol_scale)
        pnl_cal = (c5 * (1 - half_spread) - c0 * (1 + half_spread)) / (c0 * (1 + half_spread))
        # The other side: SELL the straddle at the bid, buy it back at the ask.
        # Return per $ of premium collected; real margin is several times that,
        # and the loss is uncapped, so watch the tail stats, not just the mean.
        short_cal = (c0 * (1 - half_spread) - c5 * (1 + half_spread)) / (c0 * (1 - half_spread))
        if earn:
            prev = bars[i - 1][0]
            window = {b[0] for b in bars[i + 1:i + HOLD_DAYS + 1]}
            phase = ("entry_day" if (d0 in earn or prev in earn)
                     else "in_window" if earn & window else "none")
        else:
            phase = "none" if ticker not in STOCKS else "unknown"
        path = [abs(b[1] - s0) / s0 for b in bars[i + 1:i + HOLD_DAYS + 1]]
        trades.append({
            "underlying": name, "date": d0.isoformat(), "group": group,
            "vol_mult": round(mult, 3), "iv_entry": round(iv[d0], 4), "iv_exit": round(iv[d5], 4),
            "spot_entry": round(s0, 4), "spot_exit": round(s5, 4),
            "dte_entry": (expiry - d0).days, "premium_pct": round(p0 / s0 * 100, 3),
            "move_pct": round((s5 - s0) / s0 * 100, 3), "max_move_pct": round(max(path) * 100, 3),
            "hit3": int(max(path) >= 0.03), "pnl": round(pnl, 4), "pnl_cost": round(pnl_cost, 4), "pnl_cal": round(pnl_cal, 4), "short_cal": round(short_cal, 4),
            "earnings_phase": phase, "event_day": event_day(d0),
        })
    return trades, skipped


# ── Statistics ────────────────────────────────────────────────────────────────

def stats(trades: list, key: str = "pnl") -> dict:
    """Mean P&L per trade, with significance computed on DATE averages:
    spikes cluster on market-wide days (one crash = many tickers), so
    treating each trade as independent would overstate confidence."""
    xs = [t[key] for t in trades]
    n = len(xs)
    if n == 0:
        return {"n": 0}
    by_date = defaultdict(list)
    for t in trades:
        by_date[t["date"]].append(t[key])
    dm = [sum(v) / len(v) for v in by_date.values()]
    out = {"n": n, "dates": len(dm), "mean": round(sum(xs) / n, 4),
           "median": round(statistics.median(xs), 4),
           "win_rate": round(sum(1 for x in xs if x > 0) / n, 3),
           "hit3_rate": round(sum(t["hit3"] for t in trades) / n, 3),
           "worst": round(min(xs), 4), "p05": round(sorted(xs)[int(0.05 * (n - 1))], 4)}
    if len(dm) >= 3:
        m = sum(dm) / len(dm)
        se = _newey_west_se([by_date[d] for d in sorted(by_date)], m)
        out.update(date_mean=round(m, 4), t_dates=round(m / se, 2) if se else None,
                   ci95_dates=[round(m - 1.96 * se, 4), round(m + 1.96 * se, 4)])
    return out


def _newey_west_se(groups: list, m: float, lags: int = HOLD_DAYS) -> float:
    """Std error of the mean of date-averages, allowing for the overlap of
    consecutive 5-day holds (adjacent days share most of their path)."""
    x = [sum(g) / len(g) - m for g in groups]
    n = len(x)
    var = sum(v * v for v in x) / n
    for k in range(1, min(lags, n - 1) + 1):
        cov = sum(x[t] * x[t - k] for t in range(k, n)) / n
        var += 2 * (1 - k / (lags + 1)) * cov
    return math.sqrt(max(var, 0.0) / n)


def non_overlapping(trades: list) -> list:
    """Per underlying, drop trades entered inside a previous trade's hold."""
    out, last = [], {}
    for t in sorted(trades, key=lambda x: (x["underlying"], x["date"])):
        d = datetime.date.fromisoformat(t["date"])
        prev = last.get(t["underlying"])
        if prev and (d - prev).days < 7:          # 5 trading days ~ 7 calendar
            continue
        out.append(t)
        last[t["underlying"]] = d
    return out


def summarize(all_trades: list) -> dict:
    main = [t for t in all_trades if t["underlying"] != "SPY30"]
    g = defaultdict(list)
    for t in main:
        g[t["group"]].append(t)
    res = {"groups": {}, "spike_by_underlying": {}, "spike_by_period": {},
           "spike_by_earnings": {}, "term_structure_check": {}}
    for name, ts in g.items():
        res["groups"][name] = {"pnl": stats(ts), "pnl_cost": stats(ts, "pnl_cost"),
                               "pnl_cal": stats(ts, "pnl_cal"), "short_cal": stats(ts, "short_cal"),
                               "avg_premium_pct": round(statistics.mean(t["premium_pct"] for t in ts), 3)}
    spikes = g.get("spike", [])
    res["groups"]["spike_non_overlapping"] = {k: stats(non_overlapping(spikes), k)
                                              for k in ("pnl", "pnl_cost", "pnl_cal")}
    no_ev = [t for t in spikes if not t["event_day"]]
    res["groups"]["spike_no_event_day"] = {k: stats(no_ev, k) for k in ("pnl", "pnl_cal")}
    ev = [t for t in spikes if t["event_day"]]
    res["groups"]["spike_on_event_day"] = {k: stats(ev, k) for k in ("pnl", "pnl_cal")}
    etf = [t for t in spikes if t["underlying"] not in STOCKS]
    res["groups"]["spike_etf_only"] = {k: stats(etf, k) for k in ("pnl", "pnl_cost", "pnl_cal", "short_cal")}
    etf_c = [t for t in g.get("control", []) if t["underlying"] not in STOCKS]
    res["groups"]["control_etf_only"] = {k: stats(etf_c, k) for k in ("pnl", "pnl_cost", "pnl_cal", "short_cal")}
    for u in sorted({t["underlying"] for t in spikes}):
        sub = [t for t in spikes if t["underlying"] == u]
        ctrl = [t for t in g.get("control", []) if t["underlying"] == u]
        res["spike_by_underlying"][u] = {"spike": stats(sub), "spike_cal": stats(sub, "pnl_cal"),
                                         "control_mean": stats(ctrl).get("mean"),
                                         "control_cal_mean": stats(ctrl, "pnl_cal").get("mean")}
    for lo, hi in ((2011, 2014), (2015, 2018), (2019, 2022), (2023, 2026)):
        sub = [t for t in spikes if lo <= int(t["date"][:4]) <= hi]
        ctrl = [t for t in g.get("control", []) if lo <= int(t["date"][:4]) <= hi]
        res["spike_by_period"][f"{lo}-{hi}"] = {"spike": stats(sub), "spike_cal": stats(sub, "pnl_cal"),
                                                "control": stats(ctrl), "control_cal": stats(ctrl, "pnl_cal")}
    for ph in ("entry_day", "in_window", "none"):
        sub = [t for t in spikes if t["underlying"] in STOCKS and t["earnings_phase"] == ph]
        res["spike_by_earnings"][ph] = {"pnl": stats(sub), "pnl_cal": stats(sub, "pnl_cal")}
    for grp in ("spike", "control"):
        a = [t for t in all_trades if t["underlying"] == "SPY" and t["group"] == grp]
        b = [t for t in all_trades if t["underlying"] == "SPY30" and t["group"] == grp]
        res["term_structure_check"][grp] = {"SPY_VIX9D": stats(a).get("mean"), "SPY_VIX30": stats(b).get("mean")}
    return res


# ── Calibration ───────────────────────────────────────────────────────────────

def calibrate() -> dict:
    """Model premium vs the real ATM straddle mid on today's chains."""
    out = {}
    today = datetime.date.today()
    exit_guess = today + datetime.timedelta(days=7)
    for name, idx in IV_INDEX.items():
        if name == "SPY30":
            continue
        try:
            iv = load_iv(idx)
            last_d = max(iv)
            tk = yf.Ticker(name)
            want = first_friday_on_or_after(exit_guess + datetime.timedelta(days=EXPIRY_BUFFER_DAYS))
            exps = [e for e in tk.options if datetime.date.fromisoformat(e) >= want]
            if not exps:
                continue
            exp = exps[0]
            ch = tk.option_chain(exp)
            spot = float(ch.underlying["regularMarketPrice"])
            common = sorted(set(ch.calls.strike) & set(ch.puts.strike))
            k = min(common, key=lambda s: abs(s - spot))
            c = ch.calls[ch.calls.strike == k].iloc[0]
            p = ch.puts[ch.puts.strike == k].iloc[0]
            if min(c.bid, c.ask, p.bid, p.ask) <= 0:
                continue
            mid = (c.bid + c.ask + p.bid + p.ask) / 2
            half = ((c.ask + p.ask) - (c.bid + p.bid)) / 2 / mid
            t = (datetime.date.fromisoformat(exp) - today).days / 365.0
            model = straddle_value(spot, k, t, iv[last_d])
            out[name] = {"index": idx, "index_date": last_d.isoformat(), "iv": round(iv[last_d], 4),
                         "expiry": exp, "real_mid": round(mid, 3), "model": round(model, 3),
                         "model_over_real": round(model / mid, 3), "half_spread": round(half, 4)}
            print(f"{name:5s} {idx:6s} exp {exp} real {mid:8.3f} model {model:8.3f} "
                  f"ratio {model/mid:5.2f} half-spread {half*100:4.1f}%")
            time.sleep(0.3)
        except Exception as e:
            print(f"{name}: {type(e).__name__}: {e}")
    CALIBRATION.write_text(json.dumps({"date": today.isoformat(), "underlyings": out}, indent=2))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibrate", action="store_true")
    args = ap.parse_args()
    if args.calibrate:
        calibrate()
        return

    cal = {}
    if CALIBRATION.exists():
        cal = json.loads(CALIBRATION.read_text()).get("underlyings", {})
    all_trades, skipped, scales = [], {}, {}
    for name in IV_INDEX:
        c = cal.get("SPY" if name == "SPY30" else name, {})
        # One evening's quotes: cap obviously bad spreads, and only rescale vol
        # for ETFs (single stocks' ratio swings with the earnings calendar).
        hs = min(c.get("half_spread", DEFAULT_HALF_SPREAD), 0.10)
        ratio = c.get("model_over_real", 1.0) if name not in STOCKS and name not in ("SPY30", "EWZ") else 1.0
        scale = 1.0 / min(max(ratio, 0.8), 1.25)
        try:
            tr, sk = run_underlying(name, hs, scale)
        except Exception as e:
            print(f"{name}: failed — {type(e).__name__}: {e}")
            continue
        all_trades += tr
        skipped[name] = sk
        scales[name] = (hs, scale)
        n_sp = sum(1 for t in tr if t["group"] == "spike")
        print(f"{name:5s} {len(tr):5d} days, {n_sp:3d} spikes, {sk} skipped (no vol-index print), "
              f"half-spread {hs:.3f}, vol scale {scale:.3f}")

    res = summarize(all_trades)

    # How wrong would the vol model have to be to change the answer? Re-run
    # with every vol shaved a further 10/15/20% (cheaper options = better
    # for buyers). Data is cached, so this is fast.
    sens = {}
    for cut in (0.9, 0.85, 0.8):
        tr = []
        for name, (hs, scale) in scales.items():
            if name != "SPY30":
                tr += run_underlying(name, hs, scale * cut)[0]
        sens[f"vol_x{cut}"] = {g: stats([t for t in tr if t["group"] == g], "pnl_cal")
                               for g in ("spike", "control")}
    res["vol_haircut_sensitivity"] = sens
    res["meta"] = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "model": "Black-Scholes ATM straddle priced off CBOE implied-vol indices",
        "hold_days": HOLD_DAYS, "spike_mult": SPIKE_MULT, "skipped_no_iv": skipped,
        "calibration_used": bool(cal),
    }
    RESULTS.write_text(json.dumps(res, indent=2))
    with open(TRADES, "w", newline="") as f:
        keep = [t for t in all_trades if t["group"] != "control" and t["underlying"] != "SPY30"]
        w = csv.DictWriter(f, fieldnames=list(keep[0].keys()))
        w.writeheader()
        w.writerows(keep)
    g = res["groups"]
    for k, v in res["vol_haircut_sensitivity"].items():
        print(f"{k:22s} spike {v['spike'].get('mean')} (t {v['spike'].get('t_dates')})  "
              f"control {v['control'].get('mean')}")
    for k in ("spike", "spike_non_overlapping", "spike_no_event_day", "spike_on_event_day",
              "spike_etf_only", "control_etf_only", "near", "control"):
        if k in g:
            for m in ("pnl", "pnl_cost", "pnl_cal", "short_cal"):
                if m in g[k]:
                    print(f"{k:22s} {m:9s} {json.dumps(g[k][m])}")


if __name__ == "__main__":
    main()
