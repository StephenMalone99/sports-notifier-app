"""PDC darts events where the big names play, from the curated data/darts.yaml.

There's no good free darts API, so the majors list is kept by hand
(about one update a year, when the PDC publishes its calendar).
"""
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from ..models import Event

FILE = Path(__file__).resolve().parents[2] / "data" / "darts.yaml"


def fetch(cfg) -> list[Event]:
    items = yaml.safe_load(FILE.read_text(encoding="utf-8")) or []
    events = []
    for it in items:
        start = it["start"] if isinstance(it["start"], date) else date.fromisoformat(it["start"])
        end = it.get("end") or start
        end = end if isinstance(end, date) else date.fromisoformat(end)
        detail = " · ".join(x for x in [it.get("venue"), it.get("tv")] if x)
        slug = it["name"].lower().replace(" ", "-")

        if it.get("weekly"):
            # e.g. Premier League: one entry per night instead of a 4-month block
            uk = ZoneInfo("Europe/London")
            hh, mm = (int(x) for x in str(it.get("time", "19:00")).split(":"))
            night, day = 1, start
            while day <= end:
                events.append(Event(
                    id=f"darts-{slug}-{day.isoformat()}",
                    sport="darts",
                    title=f"{it['name']} - Night {night}",
                    start=datetime.combine(day, time(hh, mm), tzinfo=uk).astimezone(timezone.utc),
                    competition=it.get("type", "PDC"),
                    detail=detail,
                    url=it.get("url", "https://www.pdc.tv/calendar/"),
                    tags=[it.get("type", "").lower(), "night"],
                ))
                night += 1
                day += timedelta(days=7)
            continue

        events.append(Event(
            id=f"darts-{start.isoformat()}-{slug}",
            sport="darts",
            title=it["name"],
            start=datetime.combine(start, time(12), tzinfo=timezone.utc),
            end=datetime.combine(end, time(23), tzinfo=timezone.utc),
            competition=it.get("type", "PDC"),
            detail=detail,
            url=it.get("url", "https://www.pdc.tv/calendar/"),
            all_day=True,
            tags=[it.get("type", "").lower()],
        ))
    return events
