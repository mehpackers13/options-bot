"""Choose one of the paired UTC schedules for the current Eastern offset."""
import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

def should_run(kind):
    if os.environ.get("GITHUB_EVENT_NAME") != "schedule":
        return True
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    summer = bool(datetime.datetime.now(ZoneInfo("America/New_York")).dst())
    expected = {"morning": "0 12 * * 1-5" if summer else "0 13 * * 1-5",
                "weekly": "0 0 * * 1" if summer else "0 1 * * 1"}[kind]
    return event.get("schedule") == expected
