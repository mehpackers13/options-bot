"""
SHARES LAB — can the volume-spike signal be traded with SHARES instead of options?

Why ask
-------
`volume_spike` (stock volume >= 3x its trailing 30-day mean) is the one signal in this
repo that survived a baseline check: 62.9% of spike days see a 3%+ move within 5 trading
days vs 43.8% on ordinary days, and ~+10pp after correcting for ticker mix.

But it does NOT pay through options. straddle_backtest.py (15 years, 17 underlyings) has
spike-day ATM straddles losing ~11%/trade after costs, and the live paper test agrees once
quotes are priced honestly (data/straddle_summary.json: spike +2.6% after costs on n=4,
near-spike -13.7%, random controls -23.5%). The reason is arithmetic: the average spike-day
straddle prices in an ~8.6% implied move, while the signal only promises 3%. You pay 8.6%
for a 3% edge.

Shares have no premium to pay and ~1-2bp of spread on liquid large caps instead of 5-25%.
So the instrument may have been the problem rather than the signal.

The catch, stated plainly
-------------------------
volume_spike is a VOLATILITY signal: it predicts that a stock moves, not which way. Shares
need direction. So this lab does not test "buy on a spike" -- that is a coin flip. It tests
whether a spike plus the DIRECTION of the spike day itself predicts continuation (momentum /
post-earnings drift), and the mirror hypothesis that it predicts reversal.

Method (deliberately the same shape as kalshi-bot/strategy_lab.py)
-----------------------------------------------------------------
  * Entry at the NEXT day's open after the signal day, exit at the close HOLD days later.
    Nothing is decided on a bar the trade could not have been placed after.
  * Costs: a round-trip spread/slippage charge in basis points, applied to every trade.
  * Clustering by DATE, not by trade. A volume spike is usually a market-wide event (Fed day,
    opex, a selloff), so 40 tickers spiking together is one observation, not 40. Ignoring this
    is the single easiest way to manufacture a fake t-statistic.
  * A baseline control: the same trade on all non-signal days, same tickers, same period.
    An edge means beating the baseline, not merely being positive.
  * Out-of-sample holdout: the newest HOLDOUT_FRAC of dates is excluded from discovery.
  * Benjamini-Hochberg FDR across every variant tested, because testing a grid of
    thresholds x holds x directions against a 95% CI passes ~1 in 20 by chance.

Nothing here trades. It writes data/shares_lab.json and data/SHARES_LAB.md.

    python shares_lab.py                 # full run, cached prices
    python shares_lab.py --years 8 --refresh
"""
import argparse, collections, datetime, json, math, statistics, sys, time
from pathlib import Path

BASE = Path(__file__).parent
CACHE = BASE / "data" / "shares_prices.pkl"
RESULTS = BASE / "data" / "shares_lab.json"
REPORT = BASE / "data" / "SHARES_LAB.md"

# Same universe as straddle_tracker.UNIVERSE, so results are comparable to the options test.
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

TRAILING_DAYS = 30
COST_BPS = 10.0          # round-trip spread+slippage, basis points. Generous for these names.
HOLDOUT_FRAC = 0.30
FDR_Q = 0.10
MIN_DATES = 30           # independent dates required before a variant can pass
MIN_EDGE_BPS = 10.0      # must beat its own baseline by this much, after costs

SPIKE_MULTS = [2.0, 3.0, 5.0]
HOLDS = [1, 3, 5]
DIRECTIONS = ["momentum", "reversal"]


# ----------------------------------------------------------------------------- data

def load_prices(years, refresh):
    import pickle
    if CACHE.exists() and not refresh:
        try:
            with open(CACHE, "rb") as f:
                px = pickle.load(f)
            print(f"prices: {len(px)} tickers from cache")
            return px
        except Exception:
            pass
    import yfinance as yf
    end = datetime.date.today()
    start = end - datetime.timedelta(days=int(years * 365.25) + TRAILING_DAYS + 10)
    print(f"prices: downloading {len(UNIVERSE)} tickers, {start} to {end} ...", flush=True)
    raw = yf.download(UNIVERSE, start=str(start), end=str(end), progress=False,
                      auto_adjust=True, group_by="ticker", threads=True)
    px = {}
    for t in UNIVERSE:
        try:
            d = raw[t].dropna()
        except Exception:
            continue
        if len(d) < TRAILING_DAYS + 20:
            continue
        px[t] = [(idx.date(), float(r["Open"]), float(r["Close"]), float(r["Volume"]))
                 for idx, r in d.iterrows() if r["Volume"] > 0]
    CACHE.parent.mkdir(exist_ok=True)
    with open(CACHE, "wb") as f:
        pickle.dump(px, f)
    print(f"prices: {len(px)} tickers cached")
    return px


# ----------------------------------------------------------------------------- trades

def build_trades(px, mult, hold, direction):
    """Signal on day i, enter at day i+1 OPEN, exit at day i+1+hold-1 CLOSE.

    Returns (signal_trades, baseline_trades) as lists of (date, net_return).
    Entry on the next open is what makes this tradeable: the spike and its direction are
    only known after day i closes."""
    sig, base = [], []
    cost = COST_BPS / 10000.0
    for t, rows in px.items():
        vols = [r[3] for r in rows]
        for i in range(TRAILING_DAYS, len(rows) - hold - 1):
            trail = vols[i - TRAILING_DAYS:i]
            m = sum(trail) / TRAILING_DAYS
            if m <= 0:
                continue
            ratio = vols[i] / m
            d_open, d_close = rows[i][1], rows[i][2]
            if d_open <= 0:
                continue
            day_ret = d_close / d_open - 1.0
            if day_ret == 0:
                continue
            entry = rows[i + 1][1]
            exit_ = rows[i + hold][2]
            if entry <= 0 or exit_ <= 0:
                continue
            raw_ret = exit_ / entry - 1.0
            # momentum: follow the signal day's direction; reversal: fade it
            side = 1 if day_ret > 0 else -1
            if direction == "reversal":
                side = -side
            net = side * raw_ret - cost
            (sig if ratio >= mult else base).append((rows[i + 1][0], net))
    return sig, base


def by_date(trades):
    """Mean return per calendar date. A spike is usually a market-wide event, so 40 tickers
    spiking on the same day is ONE observation; treating them as 40 inflates t by ~sqrt(40)."""
    d = collections.defaultdict(list)
    for dt, r in trades:
        d[dt].append(r)
    return {dt: statistics.mean(v) for dt, v in d.items()}


def stats(date_means):
    n = len(date_means)
    if n < 5:
        return None
    vals = list(date_means.values())
    m = statistics.mean(vals)
    sd = statistics.stdev(vals)
    se = sd / math.sqrt(n)
    if se > 0:
        t = m / se
        p = 2 * (1 - statistics.NormalDist().cdf(abs(t)))
    else:
        t, p = (float("inf") if m > 0 else 0.0), (0.0 if m > 0 else 1.0)
    return {"dates": n, "trades": sum(1 for _ in date_means),
            "mean_bps": round(m * 10000, 2), "lo_bps": round((m - 2 * se) * 10000, 2),
            "hi_bps": round((m + 2 * se) * 10000, 2), "t": round(t, 2), "p": p}


def bh_threshold(pvals, q=FDR_Q):
    m = len(pvals)
    if not m:
        return 0.0
    thr = 0.0
    for i, p in enumerate(sorted(pvals), start=1):
        if p <= q * i / m:
            thr = p
    return thr


# ----------------------------------------------------------------------------- main

def run(years, refresh):
    px = load_prices(years, refresh)
    if not px:
        print("no price data", file=sys.stderr)
        return
    all_dates = sorted({r[0] for rows in px.values() for r in rows})
    cut = all_dates[int(len(all_dates) * (1 - HOLDOUT_FRAC))]
    print(f"dates: {len(all_dates)} ({all_dates[0]} to {all_dates[-1]}); "
          f"holdout from {cut}", flush=True)

    out = []
    for mult in SPIKE_MULTS:
        for hold in HOLDS:
            for direction in DIRECTIONS:
                sig, base = build_trades(px, mult, hold, direction)
                sd_all, bd_all = by_date(sig), by_date(base)
                sd_in = {d: v for d, v in sd_all.items() if d < cut}
                sd_out = {d: v for d, v in sd_all.items() if d >= cut}
                bd_in = {d: v for d, v in bd_all.items() if d < cut}
                s, b = stats(sd_in), stats(bd_in)
                so = stats(sd_out)
                if not s or not b:
                    continue
                e = {"mult": mult, "hold": hold, "direction": direction,
                     "n_trades": len(sig), "signal": s, "baseline": b,
                     "holdout": so,
                     "edge_bps": round(s["mean_bps"] - b["mean_bps"], 2),
                     "p": s["p"]}
                e["gate_n"] = s["dates"] >= MIN_DATES
                e["gate_pos"] = s["mean_bps"] > 0 and s["lo_bps"] > 0
                e["gate_edge"] = e["edge_bps"] >= MIN_EDGE_BPS
                e["gate_oos"] = bool(so and so["dates"] >= 10 and so["mean_bps"] > 0)
                out.append(e)
                print(f"  {mult:.0f}x hold{hold} {direction:9s} dates {s['dates']:5d} "
                      f"net {s['mean_bps']:+8.1f}bps [{s['lo_bps']:+.0f},{s['hi_bps']:+.0f}] "
                      f"base {b['mean_bps']:+7.1f} edge {e['edge_bps']:+7.1f} "
                      f"oos {so['mean_bps'] if so else None} p={s['p']:.2g}", flush=True)

    thr = bh_threshold([e["p"] for e in out], FDR_Q)
    for e in out:
        e["gate_fdr"] = bool(e["p"] <= thr) if thr > 0 else False
        e["passed"] = bool(e["gate_n"] and e["gate_pos"] and e["gate_edge"]
                           and e["gate_oos"] and e["gate_fdr"])
    passed = [e for e in out if e["passed"]]
    out.sort(key=lambda e: -e["edge_bps"])

    res = {"generated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z",
           "tickers": len(px), "dates": len(all_dates),
           "period": [str(all_dates[0]), str(all_dates[-1])], "holdout_from": str(cut),
           "cost_bps": COST_BPS, "fdr_q": FDR_Q, "bh_threshold": round(thr, 6),
           "variants": len(out), "passed": passed, "all": out}
    RESULTS.write_text(json.dumps(res, indent=1))

    lines = [f"# Shares Lab — {res['generated']}", "",
             f"Can the volume-spike signal be traded with SHARES instead of options?",
             "",
             f"{len(px)} tickers, {len(all_dates)} trading days ({all_dates[0]} to {all_dates[-1]}), "
             f"{len(out)} variants (spike multiple x hold x momentum/reversal).",
             f"Entry is the NEXT day's open after the signal, exit the close {HOLDS} days later, "
             f"{COST_BPS:.0f}bps round-trip costs charged on every trade.",
             f"Returns are averaged per DATE before any statistic: a volume spike is usually a "
             f"market-wide event, so 40 tickers spiking together is one observation, not 40.",
             f"Discovery used dates before {cut}; later dates were held out.", "",
             f"**Variants passing every gate: {len(passed)}.** A variant must clear:", "",
             f"1. **sample** — >={MIN_DATES} independent dates;",
             f"2. **positive** — mean above 0 with the 95% CI above 0, after costs;",
             f"3. **beats baseline** — >= +{MIN_EDGE_BPS:.0f}bps vs the same trade on non-signal days;",
             f"4. **out of sample** — >=10 held-out dates, still positive there;",
             f"5. **multiple comparisons** — Benjamini-Hochberg at q={FDR_Q:.2f} across all "
             f"{len(out)} variants (cutoff p<={thr:.5f}).", "",
             "| Spike | Hold | Direction | Dates | Net (bps) | 95% range | Baseline | Edge | Holdout | p | Pass |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in out:
        s, b, o = e["signal"], e["baseline"], e["holdout"]
        lines.append(f"| {e['mult']:.0f}x | {e['hold']}d | {e['direction']} | {s['dates']} | "
                     f"{s['mean_bps']:+.1f} | [{s['lo_bps']:+.0f}, {s['hi_bps']:+.0f}] | "
                     f"{b['mean_bps']:+.1f} | {e['edge_bps']:+.1f} | "
                     f"{o['mean_bps']:+.1f} ({o['dates']}) | {e['p']:.2g} | "
                     f"{'YES' if e['passed'] else ''} |")
    lines += ["", "Paper research only. Nothing here places a trade, and a pass is a candidate "
                  "for forward testing, not a proven edge."]
    REPORT.write_text("\n".join(lines) + "\n")
    print()
    print("\n".join(lines[8:14]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=12.0)
    ap.add_argument("--refresh", action="store_true", help="re-download prices")
    a = ap.parse_args()
    run(a.years, a.refresh)


if __name__ == "__main__":
    main()
