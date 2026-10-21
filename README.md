# Options Alert Bot

Scans the configured stocks' nearest three options expirations, filters unusual
activity, records delivered alerts, and optionally sends them to Discord.
AI reports summarize manually rated alerts; they do not change thresholds or place trades.

## Run locally

Use Python 3.11 or newer. From this project's folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

Set `DISCORD_WEBHOOK_URL` in your environment to enable signal delivery. Set
`DISCORD_HEALTH_WEBHOOK_URL` for health reports. Without these values the bot
prints alerts locally. Never paste credentials into source code or a Git remote URL.
An `.env` file is not loaded automatically.

Optional settings:

| Environment variable | Purpose |
| --- | --- |
| `TRADIER_API_TOKEN` | Try Tradier data, falling back to yfinance |
| `ANTHROPIC_API_KEY` | Enable AI morning and weekly reports |
| `ANTHROPIC_MODEL` | AI model override; defaults to `claude-haiku-4-5` |

Edit `config.py` to change tickers, scan intervals, and default thresholds.
Install dependencies again after pulling updates.

## Signal behavior

- A baseline requires at least five **prior** days of recorded volume. It uses
  up to 20 previous days, excludes today, and retains 30 dates.
- The stored daily value is the highest observed cumulative volume. Missing
  scans, partial provider responses, and expiration changes can affect comparisons;
  this is not a complete historical options dataset or an intraday-normalized baseline.
- Candidates include volume spikes, IV increases, and put/call volume ratios.
  A ratio is unavailable when call volume is zero; no ratio-based signal is inferred.
- Signals must meet the 3x volume floor, historical performance rule, earnings
  handling, and a 70-point composite score. The score is a heuristic, not a
  measured probability of a profitable trade. Volume does not identify buyers versus sellers.
- Earnings proximity is date-based, not an exact 24-hour timestamp. The current
  scanner automatically tags nearby earnings as earnings plays; its earnings gate
  does not independently establish trading intent.
- Successfully delivered (or console-printed) alerts are recorded. Failed deliveries
  remain eligible on the next scan. The 60-minute duplicate check reads the CSV,
  so it survives scheduled process restarts.
- The calendar skips NYSE holidays and respects early closes. Regular scanning
  stops at the equity session close, even where some options trade later.

## Ratings and threshold tuning

In `alerts_log.csv`, set `outcome` to `1` or `0`; leave unrated alerts blank.
Tuning requires the configured minimum (currently 10) rated alerts overall and at least five for a signal type.
It adjusts thresholds by 10% within hard limits and saves a fingerprint of the
ratings with the thresholds. Unchanged ratings do not trigger repeated tuning.
New ratings permit another cycle over the accumulated sample. This is a heuristic
adjustment, not a validated learning or profitability system.

Do not run multiple local bot instances, or local and scheduled writers against
one working folder. Atomic JSON writes prevent partial files; they do not provide
cross-process transaction locking. An interruption after Discord accepts a message
but before its CSV entry is written can still produce a duplicate on retry.

## Commands

```sh
python run_once.py          # one scan, only during market hours
python self_improve.py      # statistical tuning only
python run_morning.py       # statistics + optional AI + optional Discord briefing
python run_weekly.py        # seven-day AI review + optional Discord briefing
python generate_data.py     # regenerate dashboard JSON
python -m unittest discover -s tests -v
```

## Automation and dashboard

See `SETUP_GITHUB.md`. Scan, morning, and weekly jobs share a concurrency group to
avoid simultaneous repository state writes. Paired UTC schedules select one run
for the current Eastern daylight-saving offset. GitHub scheduling can be delayed;
this is not a guaranteed real-time service.

The Pages workflow runs after successful data workflows, since pushes using
`GITHUB_TOKEN` do not normally trigger another push workflow. The dashboard escapes
inserted text and reports data freshness, not whether a bot process is alive.
Published dashboard data includes alert history and AI summaries; review it before
publishing. Old data files are retained until regenerated.

The newer project also includes VIX monitoring and `run_4pm.py` for the daily close report. VIX delivery state is persisted across scheduled runs.
