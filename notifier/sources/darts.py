"""PDC darts events where the big names play, from the curated data/darts.yaml.

There's no good free darts API, so the majors list is kept by hand
(about one update a year, when the PDC publishes its calendar).
"""
from datetime import date, datetime, time, timezone
from pathlib import Path

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
        events.append(Event(
            id=f"darts-{start.isoformat()}-{it['name'].lower().replace(' ', '-')}",
            sport="darts",
            title=it["name"],
            start=datetime.combine(start, time(12), tzinfo=timezone.utc),
            end=datetime.combine(end, time(23), tzinfo=timezone.utc),
            competition=it.get("type", "PDC"),
            detail=" · ".join(x for x in [it.get("venue"), it.get("tv")] if x),
            url=it.get("url", "https://www.pdc.tv/calendar/"),
            all_day=True,
            tags=[it.get("type", "").lower()],
        ))
    return events
