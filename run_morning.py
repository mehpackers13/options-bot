"""
run_morning.py — Morning analysis runner for GitHub Actions.
Runs at 8am ET on weekdays (see self-improve.yml).
  1. Statistical self-improvement (threshold tuning from CSV history)
  2. Claude AI analysis of last 7 days
  3. Sends morning briefing to Discord health channel
"""

import datetime
import json
import os
from pathlib import Path

import pytz
import requests

ET = pytz.timezone("America/New_York")


def _send_morning_briefing(ai_result: dict, stat_changes: int) -> None:
    webhook = os.environ.get("DISCORD_HEALTH_WEBHOOK_URL", "")
    if not webhook:
        print("[morning] No health webhook — printing briefing instead")
        print(json.dumps(ai_result, indent=2))
        return

    today = datetime.datetime.now(ET).strftime("%A, %B %-d")

    confidence = ai_result.get("confidence_in_thresholds", "medium").upper()
    conf_emoji = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(confidence, "🟡")

    watchlist = ai_result.get("premarket_watchlist", [])
    watchlist_str = ", ".join(watchlist) if watchlist else "Nothing specific"

    changes_str = (
        f"{stat_changes} threshold(s) auto-adjusted"
        if stat_changes > 0
        else "No threshold changes"
    )

    alerts_analyzed = ai_result.get("alerts_analyzed", 0)
    rated           = ai_result.get("rated_alerts", 0)

    fields = [
        {"name": "📊 Alerts Analyzed",        "value": f"{alerts_analyzed} total, {rated} rated", "inline": True},
        {"name": f"{conf_emoji} Threshold Confidence", "value": confidence, "inline": True},
        {"name": "⚙️ Threshold Changes",       "value": changes_str, "inline": True},
        {"name": "📈 What's Working",          "value": ai_result.get("patterns_working", "N/A"),   "inline": False},
        {"name": "🛑 Stop Doing",              "value": ai_result.get("stop_doing", "N/A"),          "inline": False},
        {"name": "🎯 Today's Strategy",        "value": ai_result.get("strategy_today", "N/A"),      "inline": False},
        {"name": "🔬 Try Today",               "value": ai_result.get("try_today", "N/A"),           "inline": False},
        {"name": "👀 Premarket Watchlist",      "value": watchlist_str,                               "inline": False},
    ]

    payload = {
        "embeds": [{
            "title":  f"🧠 Morning Briefing — {today}",
            "color":  0x5865F2,
            "fields": fields,
            "footer": {"text": "Options Bot — AI-powered morning analysis"},
            "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }]
    }

    try:
        resp = requests.post(webhook, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            print("[morning] Briefing sent to Discord")
        else:
            print(f"[morning] Discord error {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        print(f"[morning] Failed to send briefing: {exc}")


def main() -> None:
    print("=" * 60)
    print(f"  MORNING ANALYSIS — {datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}")
    print("=" * 60)

    # Step 1: Statistical self-improvement
    stat_changes = 0
    try:
        from self_improve import run_morning_analysis as run_stat_analysis
        run_stat_analysis()
        # Count changes from threshold_changes.log (last N lines)
        changes_log = Path(__file__).parent / "threshold_changes.log"
        if changes_log.exists():
            today_str = datetime.datetime.now(ET).strftime("%Y-%m-%d")
            today_lines = [
                l for l in changes_log.read_text().splitlines()
                if today_str in l and "CHANGE" in l
            ]
            stat_changes = len(today_lines)
    except Exception as exc:
        print(f"[morning] Statistical analysis error: {exc}")

    # Step 2: AI analysis
    ai_result = {}
    try:
        from ai_brain import run_morning_analysis as run_ai_analysis
        result = run_ai_analysis()
        if result:
            ai_result = result
    except Exception as exc:
        print(f"[morning] AI analysis error: {exc}")

    # Step 3: Morning briefing to Discord
    if ai_result:
        _send_morning_briefing(ai_result, stat_changes)
    else:
        print("[morning] No AI result — skipping Discord briefing")

    print("=" * 60)


if __name__ == "__main__":
    main()
