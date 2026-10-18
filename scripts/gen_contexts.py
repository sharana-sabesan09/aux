"""Synthesize ~1000 varied context prompts covering all passive signals (PRD §5). Writes data/contexts.jsonl."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.env import ROOT  # noqa: E402

OUT = ROOT / "data" / "contexts.jsonl"
N = 1000
random.seed(42)

TIMES = [
    ("Mon", "06:40 AM", "early morning"), ("Tue", "08:15 AM", "morning"), ("Wed", "10:50 AM", "morning"),
    ("Thu", "12:30 PM", "afternoon"), ("Fri", "02:10 PM", "afternoon"), ("Sat", "04:45 PM", "afternoon"),
    ("Sun", "06:20 PM", "evening"), ("Mon", "08:00 PM", "evening"), ("Fri", "10:15 PM", "late night"),
    ("Sat", "11:48 PM", "late night"), ("Sun", "01:22 AM", "late night"), ("Wed", "07:05 AM", "early morning"),
]
SPEEDS = [
    ("still, 0 mph", "still"), ("walking, 3 mph", "walking"), ("walking, 4 mph", "walking"),
    ("biking, 12 mph", "biking"), ("city driving, 28 mph", "city driving"),
    ("city driving, 35 mph", "city driving"), ("freeway, 68 mph", "freeway"), ("freeway, 74 mph", "freeway"),
]
PLACES = ["home", "Geisel library", "RIMAC gym", "Price Center", "unknown, moving", "unknown, still",
          "coffee shop", "dorm", "on the 5", "on the 405", "La Jolla shores", "friend's apartment"]
MOTIONS = ["stationary 2 h then started driving", "walking 12 min from home", "sitting still for 45 min",
           "just left the gym 5 min ago", "driving continuously for 25 min", "arrived 2 min ago",
           "stationary 4 h at desk", "walking between buildings"]
EVENTS_CURRENT = [None, "office hours", "study block", "lunch w/ Priya", "lab section",
                  "coffee w/ advisor", "pickup basketball"]
EVENTS_NEXT = ["Orgo midterm", "CSE 110 lecture", "dinner w/ Priya", "flight to SFO",
               "haircut", "team standup", "date night", "study session w/ Jamie",
               "doctor appt", "gym w/ Ryan", "none"]
WEATHERS = ["72F clear, bright sun", "64F clear, dark", "58F cloudy", "81F sunny, hazy",
            "68F light rain", "55F fog", "76F partly cloudy", "61F clear, dusk"]
RECENT = [
    "finished 3 (chill, indie), skipped 2 (hype, both < 20 s)",
    "finished 5 in a row (hype, party)",
    "skipped 4 of last 5 (all cinematic)",
    "finished 2 (lo-fi, focus), nothing skipped",
    "skipped 3 in a row (sad, nostalgic)",
    "finished 1 (romantic), skipped 1 (dark, 8 s)",
    "no plays in last hour",
    "finished 4 (electronic, hype), skipped 1 (acoustic, 12 s)",
]


def day_load() -> str:
    n = random.choice([0, 1, 2, 3, 4, 5, 6])
    if n == 0:
        return "today: nothing yet"
    b2b = random.choice([0, 0, 1, 2, 3]) if n > 2 else 0
    last = random.choice([5, 15, 25, 40, 70, 110])
    return f"today: {n} events" + (f", {b2b} back-to-back" if b2b else "") + f", last ended {last} min ago"


def build() -> str:
    day, hhmm, bucket = random.choice(TIMES)
    speed, _ = random.choice(SPEEDS)
    place = random.choice(PLACES)
    motion = random.choice(MOTIONS)
    weather = random.choice(WEATHERS)
    cur = random.choice(EVENTS_CURRENT)
    nxt = random.choice(EVENTS_NEXT)
    mins = random.choice([5, 10, 15, 20, 25, 40, 55, 80])
    cal = (f"current: \"{cur}\" | " if cur else "") + (f"next: \"{nxt}\" in {mins} min" if nxt != "none" else "next: nothing in 2 h")
    load = day_load()
    recent = random.choice(RECENT)
    return (f"{day} {hhmm} ({bucket}) | {place}, {speed}, {motion}\n"
            f"{weather}\n{load} | {nxt and cal}\n"
            f"recent: {recent}")


def main():
    OUT.parent.mkdir(exist_ok=True)
    seen = set()
    rows = []
    while len(rows) < N:
        txt = build()
        if txt in seen:
            continue
        seen.add(txt)
        rows.append({"context": txt})
    OUT.write_text("\n".join(json.dumps(r) for r in rows))
    print(f"wrote {len(rows)} contexts -> {OUT}")
    print("\nsample:\n" + rows[0]["context"] + "\n---\n" + rows[1]["context"])


if __name__ == "__main__":
    main()
