"""
run_weekly.py — Sunday evening weekly report for GitHub Actions.
Runs at 8pm ET every Sunday.
Sends a full-week performance review to the Discord health channel.
"""

import datetime
import json
import os

import pytz
import requests

ET = pytz.timezone("America/New_York")


def _send_weekly_report(result: dict, alert_count: int, rated: int) -> None:
    webhook = os.environ.get("DISCORD_HEALTH_WEBHOOK_URL", "")
    if not webhook:
        print("[weekly] No health webhook — printing report instead")
        print(json.dumps(result, indent=2))
        return

    now        = datetime.datetime.now(ET)
    week_label = now.strftime("Week ending %B %-d, %Y")

    hit_str = result.get("hit_rate_summary", "N/A")

    fields = [
        {"name": "📅 Period",           "value": week_label,                                    "inline": True},
        {"name": "📊 Total Alerts",     "value": str(alert_count),                              "inline": True},
        {"name": "✅ Rated",             "value": str(rated),                                    "inline": True},
        {"name": "🎯 Accuracy",          "value": hit_str,                                       "inline": False},
        {"name": "🏆 Best Signal",       "value": result.get("best_signal_type", "N/A"),         "inline": True},
        {"name": "⚠️ Worst Signal",      "value": result.get("worst_signal_type", "N/A"),        "inline": True},
        {"name": "💡 Key Lesson",        "value": result.get("key_lesson", "N/A"),               "inline": False},
        {"name": "🎯 Next Week Focus",   "value": result.get("next_week_focus", "N/A"),          "inline": False},
        {"name": "⚙️ Threshold Rec.",    "value": result.get("threshold_recommendation", "N/A"), "inline": False},
        {"name": "📝 Full Summary",      "value": result.get("full_summary", "N/A"),             "inline": False},
    ]

    payload = {
        "embeds": [{
            "title":  f"📅 Weekly Report — {week_label}",
            "color":  0xEB459E,
            "fields": fields,
            "footer": {"text": "Options Bot — Weekly Self-Review"},
            "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }]
    }

    try:
        resp = requests.post(webhook, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            print("[weekly] Report sent to Discord")
        else:
            print(f"[weekly] Discord error {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        print(f"[weekly] Failed to send report: {exc}")


def main() -> None:
    print("=" * 60)
    print(f"  WEEKLY REPORT — {datetime.datetime.now(ET).strftime('%Y-%m-%d %H:%M ET')}")
    print("=" * 60)

    result     = {}
    alert_count = 0
    rated_count = 0

    try:
        from ai_brain import run_weekly_analysis
        result = run_weekly_analysis() or {}
        alert_count = result.get("alerts_analyzed", 0)
        rated_count = result.get("rated_alerts", 0)
    except Exception as exc:
        print(f"[weekly] AI weekly analysis error: {exc}")

    _send_weekly_report(result, alert_count, rated_count)

    print("=" * 60)


if __name__ == "__main__":
    main()
