"""US regular-session schedule, including holidays and early closes."""
import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo
import pandas_market_calendars as calendars

ET = ZoneInfo("America/New_York")
@lru_cache(maxsize=16)
def session(day):
    schedule = calendars.get_calendar("NYSE").schedule(start_date=day, end_date=day)
    if schedule.empty:
        return None
    return schedule.iloc[0]["market_open"], schedule.iloc[0]["market_close"]

def market_open(now=None):
    now = now or datetime.datetime.now(ET)
    hours = session(now.astimezone(ET).date())
    return bool(hours and hours[0] <= now < hours[1])

def pre_market(now=None):
    now = now or datetime.datetime.now(ET)
    local = now.astimezone(ET)
    return bool(session(local.date()) and datetime.time(8) <= local.time().replace(tzinfo=None) < datetime.time(9,25))
