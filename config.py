"""
OPTIONS BOT — CONFIGURATION FILE
=================================
This is the only file you need to edit to get started.
Step 1: Add your Discord webhook URL (see README.md for a 2-minute guide).
Step 2: Customize your ticker list if desired.
Everything else is optional — the bot tunes itself over time.
"""

import os

# ============================================================
#  STEP 1: Paste your Discord webhook URL here
#  When running on GitHub Actions the value comes from your
#  repository secret (DISCORD_WEBHOOK_URL) automatically.
# ============================================================
DISCORD_WEBHOOK_URL = os.environ.get(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/1486226388330745968/NkZeJgc8azwz7EYNPAdBflriwhlK5WnQU4RMUVYl005042sM7UN0iSN5j9z4e5KmhNqz"
)

# ============================================================
#  OPTIONAL: Second webhook for a separate #bot-health channel
#  Leave blank ("") to skip health messages.
#  On GitHub Actions this comes from the DISCORD_HEALTH_WEBHOOK_URL secret.
# ============================================================
DISCORD_HEALTH_WEBHOOK_URL = os.environ.get("DISCORD_HEALTH_WEBHOOK_URL", "")

# ============================================================
#  STEP 2: Tickers to watch (add/remove as you like)
# ============================================================
TICKERS = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "AMD", "META", "XLK", "XLE", "XLF", "XBI"]

# ============================================================
#  Scan frequency: how often to check during market hours
#  (in minutes — default is every 15 minutes)
# ============================================================
SCAN_INTERVAL_MINUTES = 15

# ============================================================
#  Signal thresholds — the bot auto-tunes these over time.
#  You can also edit them manually here at any time.
# ============================================================
DEFAULT_THRESHOLDS = {
    # Alert if total options volume is this many times above the 20-day average
    "volume_spike_multiplier": 2.0,

    # Alert if implied volatility jumps this many percent in a single session
    "iv_jump_percent": 20.0,

    # Alert if put/call ratio is ABOVE this (heavy put buying = bearish)
    "put_call_ratio_high": 2.0,

    # Alert if put/call ratio is BELOW this (heavy call buying = bullish)
    "put_call_ratio_low": 0.5,
}

# ============================================================
#  Self-improvement: minimum rated alerts before auto-tuning
#  (you must fill in "outcome" in alerts_log.csv manually)
# ============================================================
MIN_ALERTS_FOR_IMPROVEMENT = 10

# ============================================================
#  VIX monitoring — index of market fear / expected volatility
# ============================================================
VIX_SPIKE_THRESHOLD  = 25.0   # send alert if VIX closes above this
VIX_DAILY_ALERT_HOUR = 16     # 4pm ET — daily VIX summary time
