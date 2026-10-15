"""
OPTIONS BACKTEST — volume_spike signal validation
==================================================
yfinance has rich stock PRICE + VOLUME history but historical options
chain + put/call ratio + IV data is paid. So we can rigorously
backtest ONE of the four signals today — volume_spike — because it
only needs stock volume data.

The other three (put_call_low, put_call_high, iv_jump) will need to
accumulate live grades over time (rate_alerts.py already does this
nightly). Combined with this historical backtest, we'll have a full
per-signal track record within a few weeks.

Signal spec being tested:
  volume_spike = today's volume > 3x the trailing 30-day mean
  prediction   = big absolute move in next 5 trading days (direction-agnostic)
  hit          = |next-5d max-min span| >= 3% of current price

Universe: top ~75 liquid US tickers (S&P mega-caps, high-volume ETFs).
Window:  2024-01-01 to 2024-12-31.

Outputs:
  options_backtest_results.json   — per-signal + per-ticker summary
  options_backtest_trades.csv     — every graded trigger
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import math
from pathlib import Path

try:
    import yfinance as yf
    _YF = True
except Exception:
    _YF = False


BASE = Path(__file__).parent
RESULTS = BASE / "data" / "options_backtest_results.json"
TRADES  = BASE / "data" / "options_backtest_trades.csv"
RESULTS.parent.mkdir(exist_ok=True)


# Top ~75 most-traded US tickers; broad coverage across sectors + ETFs.
UNIVERSE = [
    # Mega-caps
    "AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","AMD","INTC","AVGO",
    "QCOM","NFLX","ADBE","CRM","ORCL","CSCO","PYPL","PEP","KO","WMT",
    "JPM","BAC","WFC","GS","MS","C","V","MA","AXP","BRK-B",
    # Energy / commodities
    "XOM","CVX","COP","SLB","OXY","MRO",
    # Healthcare / pharma
    "JNJ","UNH","PFE","ABBV","MRK","LLY","GILD","AMGN","BMY",
    # Industrial / consumer
    "GE","F","GM","NKE","MCD","SBUX","DIS","HD","LOW",
    # ETFs — these are the big liquidity names
    "SPY","QQQ","IWM","DIA","XLE","XLF","XLK","XLV","XLY","XLI","XLU",
    "XLP","XBI","XRT","GLD","SLV","USO","TLT","HYG","LQD","VXX","UVXY",
]

VOLUME_SPIKE_MULT = 3.0
MOVE_WINDOW_DAYS  = 5
MOVE_THRESHOLD    = 0.03   # 3%


def _p_from_z(z: float) -> float:
    return round(2*(1 - 0.5*(1 + math.erf(abs(z)/math.sqrt(2)))), 4)


def backtest_ticker(ticker: str, start: str, end: str) -> list:
    """Returns a list of trigger events: {date, hit, max_move, direction}."""
    if not _YF:
        return []
    try:
        hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
    except Exception as e:
        print(f"  [{ticker}] fetch failed: {e}")
        return []
    if hist is None or len(hist) < 60:
        return []

    closes = hist["Close"].tolist()
    volumes = hist["Volume"].tolist()
    dates   = [d.date().isoformat() for d in hist.index]

    triggers = []
    for i in range(30, len(hist) - MOVE_WINDOW_DAYS - 1):
        vol_today = volumes[i]
        trailing  = sum(volumes[i-30:i]) / 30
        if trailing <= 0:
            continue
        if vol_today < trailing * VOLUME_SPIKE_MULT:
            continue
        # Signal fired — grade over next MOVE_WINDOW_DAYS
        base   = closes[i]
        window = closes[i+1 : i+1+MOVE_WINDOW_DAYS]
        if not window or base <= 0:
            continue
        max_up   = (max(window) - base) / base
        max_down = (min(window) - base) / base
        max_abs  = max(abs(max_up), abs(max_down))
        hit = 1 if max_abs >= MOVE_THRESHOLD else 0
        triggers.append({
            "ticker":   ticker,
            "date":     dates[i],
            "base":     round(base, 2),
            "vol_mult": round(vol_today/trailing, 2),
            "max_up":   round(max_up*100, 2),
            "max_down": round(max_down*100, 2),
            "max_abs":  round(max_abs*100, 2),
            "direction":"up" if max_up > abs(max_down) else "down",
            "hit":      hit,
        })
    return triggers


def summarize(trades: list) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    hits = sum(t["hit"] for t in trades)
    hr = hits/n
    se = math.sqrt(0.25/n)
    z  = (hr - 0.5)/se
    # Rough ROI estimate: a correct "big move" ~5-10% options play often
    # yields 50-150% on a cheap OTM call. Conservative: 70% avg win,
    # -100% avg loss.
    avg_win  = 0.70
    avg_loss = -1.00
    expectancy = hr*avg_win + (1-hr)*avg_loss
    # Per-ticker stats
    from collections import defaultdict
    by_t = defaultdict(lambda: [0, 0])
    for t in trades:
        by_t[t["ticker"]][1] += 1
        by_t[t["ticker"]][0] += t["hit"]
    per_ticker = []
    for tkr, (h, cnt) in sorted(by_t.items(), key=lambda x: -x[1][1]):
        per_ticker.append({"ticker": tkr, "n": cnt, "hits": h,
                           "hit_rate": round(h/cnt, 3) if cnt else 0})

    return {
        "n": n, "hits": hits, "hit_rate": round(hr, 4),
        "z": round(z, 3), "p": _p_from_z(z),
        "expectancy_per_bet": round(expectancy, 3),
        "note": f"Assumes options bet pays ~{avg_win*100:.0f}% on win, -100% on loss",
        "per_ticker_top": per_ticker[:20],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start",   default="2024-01-01")
    p.add_argument("--end",     default="2024-12-31")
    p.add_argument("--tickers", default=",".join(UNIVERSE))
    args = p.parse_args()

    if not _YF:
        print("yfinance not installed — pip install yfinance")
        return

    tickers = args.tickers.split(",")
    print(f"Backtesting volume_spike on {len(tickers)} tickers "
          f"from {args.start} to {args.end}...")
    all_trades = []
    for i, tkr in enumerate(tickers):
        trades = backtest_ticker(tkr, args.start, args.end)
        all_trades.extend(trades)
        if (i+1) % 10 == 0:
            print(f"  processed {i+1}/{len(tickers)} tickers, {len(all_trades)} triggers so far")
    print(f"\nDone. {len(all_trades)} volume_spike triggers graded.\n")

    summary = summarize(all_trades)
    print("="*70)
    print("  VOLUME_SPIKE BACKTEST SUMMARY")
    print("="*70)
    for k, v in summary.items():
        if k == "per_ticker_top":
            print(f"  {k}:")
            for row in v[:10]:
                print(f"    {row['ticker']:6} n={row['n']:3} hits={row['hits']:3} rate={row['hit_rate']*100:.1f}%")
        else:
            print(f"  {k}: {v}")

    with open(RESULTS, "w") as f:
        json.dump(summary, f, indent=2)
    keys = ["ticker","date","base","vol_mult","max_up","max_down","max_abs","direction","hit"]
    with open(TRADES, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for t in all_trades:
            w.writerow({k: t.get(k,"") for k in keys})
    print(f"\n✓ wrote {RESULTS} and {TRADES} ({len(all_trades)} rows)")


if __name__ == "__main__":
    main()
