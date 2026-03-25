"""
run_once.py — Single scan pass for GitHub Actions.
Runs one scan cycle and exits. Env vars DISCORD_WEBHOOK_URL and
DISCORD_HEALTH_WEBHOOK_URL override the values in config.py automatically
(via the os.environ.get() calls already in config.py).
"""

from bot import run_scan, is_market_hours, log, ensure_log_file

ensure_log_file()

if is_market_hours():
    log("GitHub Actions: market open — running scan")
    run_scan()
else:
    log("GitHub Actions: market closed — skipping scan")
