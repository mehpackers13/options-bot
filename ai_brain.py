"""
AI BRAIN — CLAUDE-POWERED PATTERN ANALYSIS
============================================
Called once per weekday morning and once per week for the full weekly report.
NEVER called on every scan — stays within GitHub Actions free tier.

Requires: ANTHROPIC_API_KEY environment variable (GitHub Secret).
Model: claude-3-5-haiku-20241022 (fast + cost-effective for daily use)
"""

import csv
import datetime
import json
import os
from pathlib import Path
from typing import Optional

import pytz

ET              = pytz.timezone("America/New_York")
BASE            = Path(__file__).parent
DATA_DIR        = BASE / "data"
ALERTS_LOG      = BASE / "alerts_log.csv"
AI_SUGGESTIONS  = DATA_DIR / "ai_suggestions.json"
AI_LOG          = BASE / "ai_brain.log"
MODEL           = "claude-3-5-haiku-20241022"


def _log(msg: str) -> None:
    ts   = datetime.datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    line = f"[{ts}] {msg}"
    print(line)
    with open(AI_LOG, "a") as f:
        f.write(line + "\n")


def _load_alerts(days: int = 7) -> list:
    if not ALERTS_LOG.exists():
        return []
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
    alerts = []
    try:
        with open(ALERTS_LOG, newline="") as f:
            for row in csv.DictReader(f):
                try:
                    ts = datetime.datetime.fromisoformat(
                        row.get("timestamp", "").replace(" ET", "")
                    )
                    if ts >= cutoff:
                        alerts.append(row)
                except Exception:
                    alerts.append(row)   # include if parse fails — better to have data
    except Exception:
        pass
    return alerts


def _format_table(alerts: list) -> str:
    if not alerts:
        return "No alerts in this period."
    lines = [
        "Timestamp        | Ticker | Signal Type          | Price    | Conf | Outcome",
        "-" * 75,
    ]
    for a in alerts:
        outcome = a.get("outcome", "").strip()
        outcome_label = "HIT ✓" if outcome == "1" else ("MISS ✗" if outcome == "0" else "unrated")
        lines.append(
            f"{a.get('timestamp','')[:16]:<16} | "
            f"{a.get('ticker',''):<6} | "
            f"{a.get('signal_type',''):<20} | "
            f"${a.get('price_at_alert','0'):<7} | "
            f"{a.get('confidence_score','?'):<4} | "
            f"{outcome_label}"
        )
    return "\n".join(lines)


def _load_thresholds() -> dict:
    p = DATA_DIR / "thresholds.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except Exception:
        return {}


def _call_claude(prompt: str) -> Optional[str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        _log("ANTHROPIC_API_KEY not set — skipping AI analysis")
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg    = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text.strip()
    except ImportError:
        _log("anthropic package not installed — skipping")
        return None
    except Exception as exc:
        _log(f"Claude API call failed: {exc}")
        return None


def _parse_json_response(raw: str) -> Optional[dict]:
    if not raw:
        return None
    # Strip markdown code fences if present
    clean = raw.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    clean = clean.strip()
    try:
        return json.loads(clean)
    except Exception:
        _log(f"Failed to parse AI JSON response: {clean[:200]}")
        return None


# ── Morning analysis ────────────────────────────────────────────────────────────

def run_morning_analysis() -> Optional[dict]:
    """
    Analyzes the past 7 days of signals and returns structured suggestions.
    Saves result to data/ai_suggestions.json.
    """
    DATA_DIR.mkdir(exist_ok=True)
    alerts     = _load_alerts(days=7)
    thresholds = _load_thresholds()
    rated      = [a for a in alerts if a.get("outcome") in ("0", "1")]

    _log(f"Morning AI analysis — {len(alerts)} alerts, {len(rated)} rated")

    today = datetime.datetime.now(ET).strftime("%A, %B %-d %Y")

    prompt = f"""You are the analytical brain of a disciplined, selective options alert bot. Today is {today}.

Here is the alert history from the past 7 days:

{_format_table(alerts)}

Current signal thresholds: {json.dumps(thresholds, indent=2) if thresholds else "Using defaults (volume 3x, IV 20%, P/C 2.0/0.5)"}

Total alerts this week: {len(alerts)}
Rated alerts (with known outcome): {len(rated)}

Your job is to be ruthlessly honest and data-driven. Respond in valid JSON only (no markdown, no commentary outside the JSON):

{{
  "patterns_working": "One sentence: what signal types and conditions are producing the best results (or 'Insufficient data to conclude' if less than 5 rated alerts)",
  "stop_doing": "One sentence: what to stop, reduce, or watch out for",
  "try_today": "One specific actionable thing to test or watch for today",
  "strategy_today": "One sentence describing the recommended strategy posture for today",
  "confidence_in_thresholds": "high|medium|low",
  "premarket_watchlist": ["TICKER1", "TICKER2"],
  "summary": "Two sentences max summarizing this week's bot performance honestly"
}}

If there is not enough data, say so honestly. Never invent patterns that aren't in the data."""

    raw    = _call_claude(prompt)
    result = _parse_json_response(raw)

    if result is None:
        result = {
            "patterns_working": "Insufficient data or AI unavailable.",
            "stop_doing":        "N/A",
            "try_today":         "N/A",
            "strategy_today":    "Running standard thresholds — no AI adjustment today.",
            "confidence_in_thresholds": "medium",
            "premarket_watchlist": [],
            "summary": "AI analysis unavailable today.",
        }

    result["generated_at"]    = datetime.datetime.utcnow().isoformat() + "Z"
    result["alerts_analyzed"] = len(alerts)
    result["rated_alerts"]    = len(rated)
    result["type"]             = "morning"

    with open(AI_SUGGESTIONS, "w") as f:
        json.dump(result, f, indent=2)

    _log(f"Morning analysis saved — confidence: {result.get('confidence_in_thresholds')}")
    return result


# ── Weekly analysis ─────────────────────────────────────────────────────────────

def run_weekly_analysis() -> Optional[dict]:
    """
    Deep analysis of the past 30 days for the Sunday evening report.
    """
    DATA_DIR.mkdir(exist_ok=True)
    alerts     = _load_alerts(days=30)
    thresholds = _load_thresholds()
    rated      = [a for a in alerts if a.get("outcome") in ("0", "1")]
    hits       = [a for a in rated  if a.get("outcome") == "1"]

    _log(f"Weekly AI analysis — {len(alerts)} alerts in 30 days, {len(rated)} rated")

    hit_rate_str = (
        f"{len(hits)}/{len(rated)} = {len(hits)/len(rated)*100:.0f}%"
        if rated else "no rated alerts yet"
    )

    prompt = f"""You are the analytical brain of a disciplined options alert bot writing its weekly performance review.

PAST 30 DAYS OF ALERTS:
{_format_table(alerts)}

Overall hit rate: {hit_rate_str}
Current thresholds: {json.dumps(thresholds, indent=2) if thresholds else "Using defaults"}

Write an honest weekly review. Respond in valid JSON only:

{{
  "weekly_headline": "One sentence describing this week's performance",
  "hit_rate_summary": "One sentence on overall accuracy",
  "best_signal_type": "The signal type with the best hit rate this week, or 'N/A'",
  "worst_signal_type": "The signal type with the worst hit rate this week, or 'N/A'",
  "key_lesson": "The single most important thing learned this week",
  "next_week_focus": "One concrete thing to focus on next week",
  "threshold_recommendation": "Should thresholds be tightened, loosened, or held? Why (one sentence)?",
  "full_summary": "3–4 sentence narrative summary of the week — honest, concise, no fluff"
}}

Be honest. A week with zero alerts because nothing qualified is a success. Say so if that's the case."""

    raw    = _call_claude(prompt)
    result = _parse_json_response(raw)

    if result is None:
        result = {
            "weekly_headline":           "Weekly AI analysis unavailable.",
            "hit_rate_summary":          hit_rate_str,
            "best_signal_type":          "N/A",
            "worst_signal_type":         "N/A",
            "key_lesson":                "N/A",
            "next_week_focus":           "N/A",
            "threshold_recommendation":  "N/A",
            "full_summary":              "AI analysis unavailable this week.",
        }

    result["generated_at"]    = datetime.datetime.utcnow().isoformat() + "Z"
    result["alerts_analyzed"] = len(alerts)
    result["rated_alerts"]    = len(rated)
    result["type"]             = "weekly"

    weekly_path = DATA_DIR / "ai_weekly.json"
    with open(weekly_path, "w") as f:
        json.dump(result, f, indent=2)

    _log("Weekly analysis saved")
    return result
