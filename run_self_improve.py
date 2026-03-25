"""
run_self_improve.py — One-shot self-improvement for GitHub Actions.
Reads alerts_log.csv, analyses hit rates, and adjusts thresholds if needed.
Env vars DISCORD_WEBHOOK_URL / DISCORD_HEALTH_WEBHOOK_URL are picked up
automatically via config.py.
"""

from self_improve import run_morning_analysis

run_morning_analysis()
