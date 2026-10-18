"""Build the context text block that goes to the vibe model. Live collectors: time, calendar, weather, places, recent plays."""
import json
import math
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from icalendar import Calendar

from app.env import ROOT

DEFAULT_LAT = float(os.environ.get("DEFAULT_LAT", "34.0689"))
DEFAULT_LON = float(os.environ.get("DEFAULT_LON", "-118.4452"))

_cal_cache: tuple[float, list[dict]] = (0.0, [])
_wx_cache: tuple[float, tuple[float, float], str] = (0.0, (0.0, 0.0), "")
_place_cache: dict[tuple[float, float], tuple[float, str]] = {}

# Demo-only: make up a plausible UCLA-campus GPS spot + speed per calendar-event keyword, so a fake
# calendar (no real phone GPS) still drives the model toward a different place/speed per activity.
# First keyword match wins; order matters (e.g. "gym" before "class").
_CAMPUS_SPOTS: list[tuple[tuple[str, ...], tuple[float, float, float | None]]] = [
    (("gym", "workout", "basketball", "rec", "run", "swim"), (34.0706, -118.4473, 2.8)),      # Wooden Center, jogging
    (("lecture", "class", "lab", "section", "discussion", "exam", "midterm", "final"),
     (34.0689, -118.4417, 1.2)),                                                               # Boelter Hall, walking
    (("study", "library", "homework", "hw", "office hours", "reading"), (34.0719, -118.4412, 0.0)),  # Powell Library, still
    (("lunch", "dinner", "breakfast", "food", "dining", "coffee"), (34.0735, -118.4531, 1.2)),  # De Neve Plaza, walking
    (("meeting", "club", "interview", "career"), (34.0707, -118.4434, 1.2)),                   # Ackerman Union, walking
    (("party", "social", "hang", "friends"), (34.0747, -118.4486, 1.0)),                       # Sunset Rec, walking
    (("drive", "commute", "errand"), (34.0633, -118.4455, 13.0)),                               # Westwood Blvd, city driving
]


def _campus_override(title: str) -> tuple[float, float, float | None] | None:
    t = title.lower()
    for keywords, spot in _CAMPUS_SPOTS:
        if any(k in t for k in keywords):
            return spot
    return None


def build(ctx: dict) -> str:
    return (f"{ctx['day']} {ctx['time']} ({ctx['bucket']}) | {ctx['place']}, {ctx['speed']}, {ctx['motion']}\n"
            f"{ctx['weather']}\n{ctx['day_load']} | {ctx['cal']}\nrecent: {ctx['recent']}")


def _bucket(hour: int) -> str:
    if hour < 6: return "late night"
    if hour < 10: return "early morning"
    if hour < 12: return "morning"
    if hour < 17: return "afternoon"
    if hour < 21: return "evening"
    return "late night"


def _speed_bucket(mps: float | None) -> str:
    if mps is None: return "still, unknown"
    mph = mps * 2.237
    if mph < 1: return "still, 0 mph"
    if mph < 5: return f"walking, {mph:.0f} mph"
    if mph < 15: return f"biking, {mph:.0f} mph"
    if mph < 45: return f"city driving, {mph:.0f} mph"
    return f"freeway, {mph:.0f} mph"


def _place(lat: float, lon: float) -> str:
    key = (round(lat, 4), round(lon, 4))
    cached = _place_cache.get(key)
    if cached and time.time() - cached[0] < 900:
        return cached[1]
    try:
        r = httpx.get("https://nominatim.openstreetmap.org/reverse", params={
            "lat": lat, "lon": lon, "format": "json", "zoom": 18, "addressdetails": 1,
        }, headers={"User-Agent": "aux-dj/0.1 (hackathon)"}, timeout=5)
        r.raise_for_status()
        j = r.json()
        a = j.get("address", {})
        spot = (a.get("amenity") or a.get("building") or a.get("shop") or a.get("leisure")
                or a.get("tourism") or a.get("road"))
        area = a.get("neighbourhood") or a.get("suburb") or a.get("city_district") or a.get("city") or a.get("town")
        name = ", ".join(x for x in (spot, area) if x) or j.get("display_name", "unknown").split(",")[0]
        _place_cache[key] = (time.time(), name)
        return name
    except Exception as e:
        print(f"reverse geocode failed: {e}")
        return cached[1] if cached else f"{lat:.3f},{lon:.3f}"


def _fetch_calendar() -> list[dict]:
    global _cal_cache
    if time.time() - _cal_cache[0] < 300:
        return _cal_cache[1]
    url = os.environ.get("ICAL_URL")
    if not url:
        return []
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True)
        r.raise_for_status()
        cal = Calendar.from_ical(r.text)
        now = datetime.now().astimezone()
        events = []
        for comp in cal.walk("vevent"):
            try:
                dtstart = comp.decoded("dtstart")
                dtend = comp.decoded("dtend") if comp.get("dtend") else dtstart + timedelta(hours=1)
                if hasattr(dtstart, "astimezone"):
                    dtstart = dtstart.astimezone()
                    dtend = dtend.astimezone()
                else:
                    continue
                if dtend < now - timedelta(hours=12) or dtstart > now + timedelta(hours=24):
                    continue
                events.append({"title": str(comp.get("summary", "")), "start": dtstart, "end": dtend})
            except Exception:
                continue
        events.sort(key=lambda e: e["start"])
        _cal_cache = (time.time(), events)
        return events
    except Exception as e:
        print(f"calendar fetch failed: {e}")
        return _cal_cache[1]


def _current_event(now: datetime) -> dict | None:
    events = _fetch_calendar()
    return next((e for e in events if e["start"] <= now <= e["end"]), None)


def _calendar_text(now: datetime) -> str:
    events = _fetch_calendar()
    current = _current_event(now)
    future = [e for e in events if e["start"] > now and e["start"] <= now + timedelta(hours=2)]
    parts = []
    if current:
        parts.append(f'current: "{current["title"]}"')
    if future:
        nxt = future[0]
        mins = int((nxt["start"] - now).total_seconds() / 60)
        parts.append(f'next: "{nxt["title"]}" in {mins} min')
    if not parts:
        parts.append("next: nothing in 2 h")
    return " | ".join(parts)


def _day_load_text(now: datetime) -> str:
    events = _fetch_calendar()
    today = now.date()
    today_events = [e for e in events if e["start"].date() == today and e["end"] < now]
    if not today_events:
        return "today: nothing yet"
    b2b = 0
    for a, b in zip(today_events, today_events[1:]):
        if (b["start"] - a["end"]).total_seconds() < 15 * 60:
            b2b += 1
    last_end = max(e["end"] for e in today_events)
    mins_since = max(0, int((now - last_end).total_seconds() / 60))
    out = f"today: {len(today_events)} events"
    if b2b:
        out += f", {b2b} back-to-back"
    out += f", last ended {mins_since} min ago"
    return out


def _weather(lat: float, lon: float) -> str:
    global _wx_cache
    now = time.time()
    if now - _wx_cache[0] < 900 and _wx_cache[1] == (lat, lon):
        return _wx_cache[2]
    try:
        r = httpx.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon, "current": "temperature_2m,weather_code,is_day",
            "temperature_unit": "fahrenheit",
        }, timeout=8)
        r.raise_for_status()
        c = r.json()["current"]
        code = c["weather_code"]
        cond = ("clear" if code == 0 else "partly cloudy" if code <= 3 else "fog" if code <= 48
                else "rain" if code <= 67 else "snow" if code <= 77 else "showers" if code <= 82 else "storm")
        light = "bright" if c["is_day"] else "dark"
        txt = f"{int(c['temperature_2m'])}F {cond}, {light}"
        _wx_cache = (now, (lat, lon), txt)
        return txt
    except Exception as e:
        print(f"weather fetch failed: {e}")
        return _wx_cache[2] or "weather unknown"


def _recent_text(play_log: list[dict]) -> str:
    if not play_log:
        return "no plays in last hour"
    recent = play_log[-5:]
    finished = [p for p in recent if p["outcome"] == "finish"]
    skipped = [p for p in recent if p["outcome"] in ("skip", "strong_skip")]
    parts = []
    if finished:
        parts.append(f"finished {len(finished)}")
    if skipped:
        early = [p for p in skipped if p["outcome"] == "strong_skip"]
        detail = ", ".join(f"{int(p['listened_ms']/1000)}s" for p in early[:2]) if early else ""
        parts.append(f"skipped {len(skipped)}" + (f" (both < 20 s)" if detail and len(early) >= 2 else ""))
    return ", ".join(parts) if parts else "no plays in last hour"


def live_ctx(lat: float | None = None, lon: float | None = None, speed_mps: float | None = None,
             play_log: list[dict] | None = None) -> dict:
    now = datetime.now().astimezone()
    current = _current_event(now)
    override = _campus_override(current["title"]) if current else None
    if override:
        lat, lon, speed_mps = override
    lat = lat if lat is not None else DEFAULT_LAT
    lon = lon if lon is not None else DEFAULT_LON
    return {
        "day": now.strftime("%a"),
        "time": now.strftime("%I:%M %p").lstrip("0"),
        "bucket": _bucket(now.hour),
        "place": _place(lat, lon),
        "speed": _speed_bucket(speed_mps),
        "motion": "live signal",
        "weather": _weather(lat, lon),
        "day_load": _day_load_text(now),
        "cal": _calendar_text(now),
        "recent": _recent_text(play_log or []),
    }
