"""
NEWS & SENTIMENT SCANNER
========================
Only called when a signal has ALREADY passed all four gates.
This keeps API usage minimal and free-tier friendly.

Uses:
  • yfinance built-in news (free, no key)
  • Reddit public JSON API (free, no key, no account)
"""

import time
from typing import Optional

import requests
import yfinance as yf

_HEADERS = {
    "User-Agent": "options-alert-bot/2.0 (github.com/mehpackers13/options-bot)"
}

# ── News ────────────────────────────────────────────────────────────────────────

def get_recent_news(ticker: str, limit: int = 5) -> list:
    """Return list of recent news dicts with 'title', 'publisher', 'link'."""
    try:
        items = yf.Ticker(ticker).news or []
        results = []
        for item in items[:limit]:
            results.append({
                "title":     item.get("title", ""),
                "publisher": item.get("publisher", ""),
                "link":      item.get("link", ""),
            })
        return results
    except Exception:
        return []


# ── Reddit ──────────────────────────────────────────────────────────────────────

def get_reddit_sentiment(ticker: str) -> dict:
    """
    Search r/wallstreetbets and r/options for ticker mentions today.
    Returns {'label': 'bullish'|'bearish'|'neutral', 'score': float, 'post_count': int}.
    No auth needed — uses Reddit's public JSON endpoint.
    """
    subreddits  = ["wallstreetbets", "options"]
    all_posts   = []

    for sub in subreddits:
        try:
            url  = (
                f"https://www.reddit.com/r/{sub}/search.json"
                f"?q={ticker}&sort=new&limit=10&t=day&restrict_sr=1"
            )
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            if resp.status_code == 200:
                children = resp.json().get("data", {}).get("children", [])
                for child in children:
                    d = child.get("data", {})
                    all_posts.append({
                        "title":        d.get("title", ""),
                        "score":        d.get("score", 0),
                        "upvote_ratio": d.get("upvote_ratio", 0.5),
                        "subreddit":    sub,
                    })
            time.sleep(0.8)   # polite to Reddit
        except Exception:
            pass

    if not all_posts:
        return {"label": "neutral", "score": 0.0, "post_count": 0}

    BULLISH = ["calls", "call", "buy", "long", "moon", "bullish", "breakout",
               "squeeze", "yolo", "🚀", "rip", "pumping"]
    BEARISH = ["puts", "put", "short", "bearish", "dump", "crash", "sell",
               "drop", "collapse", "🌈🐻", "bear", "hedge"]

    sentiment = 0.0
    for post in all_posts:
        t   = post["title"].lower()
        b   = sum(1 for w in BULLISH if w in t)
        br  = sum(1 for w in BEARISH if w in t)
        w   = 1.0 + post.get("upvote_ratio", 0.5)
        sentiment += (b - br) * w

    label = "neutral"
    if sentiment > 3:
        label = "bullish"
    elif sentiment < -3:
        label = "bearish"

    return {"label": label, "score": round(sentiment, 1), "post_count": len(all_posts)}


# ── Combined summary ─────────────────────────────────────────────────────────────

def build_context_summary(ticker: str) -> str:
    """
    Returns a one-paragraph context blurb for the Discord alert.
    Only called for signals that passed all four gates.
    """
    news      = get_recent_news(ticker, limit=3)
    sentiment = get_reddit_sentiment(ticker)

    parts = []

    if news:
        headlines = "; ".join(f'"{n["title"]}"' for n in news if n["title"])
        parts.append(f"**Recent news:** {headlines}.")

    label      = sentiment["label"].upper()
    post_count = sentiment["post_count"]
    score      = sentiment["score"]
    if post_count > 0:
        parts.append(
            f"**Reddit ({post_count} posts today):** "
            f"Sentiment {label} (score {score:+.1f} across "
            f"r/wallstreetbets & r/options)."
        )
    else:
        parts.append("**Reddit:** No significant chatter today.")

    return "  ".join(parts) if parts else "No additional context available."
