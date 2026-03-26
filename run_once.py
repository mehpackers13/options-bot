"""
run_once.py — Single scan pass for GitHub Actions.
Runs one scan, exits. Env vars from GitHub Secrets override config.py values.
"""

import data_sources
from bot import run_scan, is_market_hours, log, ensure_log_file

data_sources.init()
ensure_log_file()

if is_market_hours():
    log("GitHub Actions: market open — running scan")
    run_scan()
else:
    log("GitHub Actions: market closed — skipping scan (schedule ran early/late)")
