"""Formula 1 sessions from the Jolpica F1 API (free, no key; the Ergast successor).

Each race weekend becomes one event per session you care about
(qualifying, sprint, race... set in config.yaml under f1.sessions).
"""
import logging
from datetime import datetime, timezone

import requests

from ..models import Event

log = logging.getLogger("notifier")
BASE = "https://api.jolpi.ca/ergast/f1"

# Jolpica field -> friendly name
SESSIONS = {
    "FirstPractice": "Practice 1",
    "SecondPractice": "Practice 2",
    "ThirdPractice": "Practice 3",
    "SprintQualifying": "Sprint Qualifying",
    "SprintShootout": "Sprint Qualifying",   # older name for the same session
    "Sprint": "Sprint",
    "Qualifying": "Qualifying",
    "Race": "Race",
}


def _when(d: dict) -> datetime | None:
    if not d or not d.get("date"):
        return None
    t = (d.get("time") or "12:00:00Z").replace("Z", "+00:00")
    if "+" not in t:
        t += "+00:00"
    return datetime.fromisoformat(f"{d['date']}T{t}").astimezone(timezone.utc)


def _season(year) -> list[dict]:
    r = requests.get(f"{BASE}/{year}.json", params={"limit": 100}, timeout=20)
    r.raise_for_status()
    return r.json()["MRData"]["RaceTable"]["Races"]


def fetch(cfg) -> list[Event]:
    wanted = set(cfg.get("sessions", ["Sprint Qualifying", "Sprint", "Qualifying", "Race"]))
    tv = cfg.get("tv", "")
    now = datetime.now(timezone.utc)

    races = _season("current")
    # Late in the year, also look at next season once it's published
    upcoming = [r for r in races if (_when(r) or now) >= now]
    if len(upcoming) < 3:
        try:
            races += _season(now.year + 1)
        except Exception:
            pass

    events = []
    for race in races:
        circuit = race.get("Circuit", {})
        loc = circuit.get("Location", {})
        place = ", ".join(x for x in [circuit.get("circuitName"), loc.get("country")] if x)
        sprint_weekend = "Sprint" in race
        sessions = {k: race.get(k) for k in SESSIONS if k in race}
        sessions["Race"] = {"date": race.get("date"), "time": race.get("time")}
        for key, data in sessions.items():
            name = SESSIONS[key]
            if name not in wanted:
                continue
            start = _when(data)
            if not start:
                continue
            events.append(Event(
                id=f"f1-{race['season']}-{race['round']}-{key.lower()}",
                sport="f1",
                title=f"{race['raceName']} - {name}",
                start=start,
                competition=f"F1 Round {race['round']}" + (" · Sprint weekend" if sprint_weekend else ""),
                detail=place,
                url=race.get("url") or "https://www.formula1.com/en/racing",
                tags=[f"session:{name}"] + ([f"tv:{tv}"] if tv else []),
            ))
    return list({e.id: e for e in events}.values())
