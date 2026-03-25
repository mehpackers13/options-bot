# Options Alert Bot

A self-improving Python bot that scans options activity for SPY, QQQ, AAPL, TSLA, and NVDA (customizable), sends alerts to Discord, and automatically tunes its own signal thresholds over time based on your feedback.

---

## Quick Start (5 minutes)

### Step 1 — Install Python dependencies

Open Terminal and paste this command:

```bash
cd ~/Desktop/options-bot
pip install -r requirements.txt
```

If `pip` isn't found, try `pip3` instead.

---

### Step 2 — Set up your Discord webhook (2 minutes)

You need a free Discord server and a webhook URL. Here's how:

1. Open Discord and go to any server you own (or create a new one — it's free).
2. Right-click a text channel → **Edit Channel**.
3. Click **Integrations** → **Webhooks** → **New Webhook**.
4. Give it a name like `Options Bot`, click **Copy Webhook URL**.
5. Open `config.py` in any text editor (TextEdit works fine).
6. Replace `YOUR_DISCORD_WEBHOOK_URL_HERE` with the URL you just copied.

That's it — you'll now receive rich alerts directly in that Discord channel.

**Don't have Discord?** No problem. Leave the webhook URL as-is and alerts will print to the Terminal window instead.

---

### Step 3 — Run the bot

```bash
cd ~/Desktop/options-bot
python run.py
```

The bot will:
- Print a startup message listing your tickers
- Wait if the market is currently closed (comes back automatically)
- Scan every 15 minutes during market hours (9:30am–4pm ET, Mon–Fri)
- Send a Discord alert (or print to Terminal) whenever a signal fires

To stop the bot, press **Ctrl+C** in the Terminal window.

---

## Customizing Your Ticker List

Open `config.py` and edit the `TICKERS` list:

```python
TICKERS = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMZN", "META"]
```

Any US stock or ETF with options will work. Keep the list under ~15 tickers to avoid slow scans.

---

## What Each Signal Means

| Signal | What it detects | What it might indicate |
|---|---|---|
| **Options Volume Spike** | Total options volume is 3x+ the 20-day average | Smart money is positioning aggressively |
| **IV Spike** | Implied volatility jumps 20%+ in a single session | Market expects a big move (earnings, news) |
| **Bearish Put/Call Skew** | Put/Call ratio above 2.0 | Heavy put buying — traders expect a drop |
| **Bullish Put/Call Skew** | Put/Call ratio below 0.5 | Heavy call buying — traders expect a rise |

### What is the confidence score?

Each alert includes a score from 0–100 that reflects how strongly the signal triggered relative to its threshold. A 90/100 means the signal was nearly double the threshold — much more notable than a 52/100 that barely crossed the line.

---

## Files Created by the Bot

| File | Purpose |
|---|---|
| `alerts_log.csv` | Every alert ever fired — **you fill in the "outcome" column** |
| `bot.log` | Full log of every scan and alert |
| `threshold_changes.log` | Audit trail of every automatic threshold adjustment |
| `data/history.json` | Rolling 30-day options volume and IV history |
| `data/thresholds.json` | Current auto-tuned thresholds (overrides config.py defaults) |

---

## How the Self-Improvement Loop Works

### 1. You rate your alerts

Open `alerts_log.csv` (it opens in Excel or Numbers). You'll see one row per alert. The last column is `outcome` — leave it blank by default, then come back and fill it in:

- `1` = the alert was **correct** (the stock made a notable move in the expected direction)
- `0` = the alert was a **false positive** (nothing happened)

You don't need to rate every alert — just the ones you followed up on.

### 2. The bot analyzes overnight

Each morning between **8:00–9:25am ET**, the bot automatically:
- Counts how many alerts for each signal type were correct vs wrong
- Calculates the **hit rate** (% correct) for each signal
- Adjusts thresholds if a signal's hit rate is outside the 45–80% target range:
  - **Hit rate too low (< 45%)** → raises the threshold (harder to trigger, fewer false positives)
  - **Hit rate too high (> 80%)** → lowers the threshold slightly (fires more often to catch more moves)
- Logs every change with an explanation to `threshold_changes.log`

### 3. Thresholds update gradually

Adjustments are conservative — only **10% per cycle** — so the bot moves thoughtfully rather than overcorrecting. Hard limits prevent thresholds from going to unreasonable extremes.

### Minimum sample requirement

The bot won't touch thresholds until you've rated at least **20 alerts** (set in `config.py` as `MIN_ALERTS_FOR_IMPROVEMENT`). This prevents premature tuning on too little data.

### Run analysis manually any time

```bash
python self_improve.py
```

This shows you the current signal stats and applies any warranted adjustments immediately.

---

## Resetting Thresholds

If you want to go back to the original defaults, delete `data/thresholds.json` and restart the bot.

---

## Troubleshooting

**"No module named yfinance"**
→ Run `pip install -r requirements.txt` again.

**"Discord returned 400"**
→ Your webhook URL is invalid. Double-check you copied the full URL from Discord.

**Bot shows no signals after running for days**
→ The volume spike signal needs 5+ days of history to calibrate. Give it a few trading days.
→ You can also lower `volume_spike_multiplier` in `config.py` to make it more sensitive.

**Alerts firing too often / too rarely**
→ Edit thresholds directly in `config.py`, or rate more alerts so the self-improvement loop can tune them automatically.

**"Rate limited" or slow scans**
→ yfinance is a free, unofficial API. If scans slow down, add more tickers to the `TICKERS` list gradually, or increase `SCAN_INTERVAL_MINUTES`.

---

## Project Structure

```
options-bot/
├── run.py              ← START HERE: python run.py
├── config.py           ← Your settings (webhook URL, tickers, thresholds)
├── bot.py              ← Main scanner (don't need to edit)
├── self_improve.py     ← Self-improvement engine (don't need to edit)
├── requirements.txt    ← Python dependencies
├── alerts_log.csv      ← Created automatically; you fill in "outcome"
├── bot.log             ← Created automatically
├── threshold_changes.log ← Created automatically
└── data/
    ├── history.json    ← Rolling IV and volume history
    └── thresholds.json ← Auto-tuned thresholds
```

---

## Data Source

All data comes from **yfinance**, which pulls free real-time (15-min delayed) options data from Yahoo Finance. No API key, no subscription, no cost.

Options data may occasionally be unavailable for low-volume tickers or outside of market hours. The bot handles this gracefully and logs any issues.
