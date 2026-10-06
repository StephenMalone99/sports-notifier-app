"""PDC darts: the event calendar from data/darts.yaml, plus match-ups and times
from the SportsAPI Pro darts API on event days.

The calendar is kept by hand (about one update a year). On days a PDC event in
that calendar is on, the free SportsAPI Pro plan (100 requests/day) is asked
for that day's schedule, so you see who plays who and when. On other days no
API calls are made.
"""
import logging
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

from ..keystore import get_secret
from ..models import Event

log = logging.getLogger("notifier")
API = "https://api.sportsapipro.com/v2/darts"

FILE = Path(__file__).resolve().parents[2] / "data" / "darts.yaml"


def _calendar(cfg) -> list[Event]:
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


# ---------------- match-ups from SportsAPI Pro ----------------
DEFAULT_EXCLUDE = ["modus", "challenge tour", "development tour", "women", "youth", "wdf", "super series"]


def _active_today(calendar: list[Event], today) -> list[Event]:
    return [e for e in calendar
            if e.start.astimezone(timezone.utc).date() <= today <= (e.end or e.start).date()]


def _schedule(key: str, day: str) -> list:
    headers = {"x-api-key": key, "Accept": "application/json"}
    for path in (f"{API}/api/schedule/{day}", f"{API}/schedule/{day}"):   # documented path first
        r = requests.get(path, headers=headers, timeout=20)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            data = data.get("events") or data.get("data") or data.get("matches") or []
        return data if isinstance(data, list) else []
    return []


def _wanted(ev: dict, active: list[Event], cfg) -> bool:
    t = ev.get("tournament") or {}
    name = " ".join(x for x in [t.get("name"), (t.get("uniqueTournament") or {}).get("name")] if x).lower()
    if any(x in name for x in (cfg.get("exclude") or DEFAULT_EXCLUDE)):
        return False
    def norm(x):
        x = x.lower()
        for w in ("pdc", "darts", "the"):
            x = x.replace(w, " ")
        return " ".join(x.split())
    name = norm(name)
    keys = [norm(a.title.split(" - ")[0]) for a in active]
    keys += [norm(k) for k in (cfg.get("include") or [])]
    return any(k and k in name for k in keys)


def _matches(cfg, active: list[Event], today) -> list[Event]:
    key = get_secret("SPORTSAPIPRO_KEY")
    if not key:
        return []
    out = []
    for ev in _schedule(key, today.isoformat()):
        if not _wanted(ev, active, cfg) or not ev.get("startTimestamp"):
            continue
        home = (ev.get("homeTeam") or {}).get("name") or "TBD"
        away = (ev.get("awayTeam") or {}).get("name") or "TBD"
        status = (ev.get("status") or {}).get("type", "")
        score = ""
        if status in ("inprogress", "finished"):
            hs, as_ = (ev.get("homeScore") or {}).get("display"), (ev.get("awayScore") or {}).get("display")
            if hs is not None and as_ is not None:
                score = ("LIVE " if status == "inprogress" else "FT ") + f"{hs}-{as_}"
        rnd = (ev.get("roundInfo") or {}).get("name") or ""
        t = ev.get("tournament") or {}
        out.append(Event(
            id=f"darts-m-{ev.get('id')}",
            sport="darts",
            title=f"{home} vs {away}",
            start=datetime.fromtimestamp(ev["startTimestamp"], tz=timezone.utc),
            competition=(t.get("uniqueTournament") or {}).get("name") or t.get("name") or "PDC",
            detail=" · ".join(x for x in [rnd, score] if x),
            url="https://www.pdc.tv/",
            tags=["match", f"sap:{ev.get('id')}", f"round:{rnd}"]
                 + (["finished", f"score:{(ev.get('homeScore') or {}).get('display')}-"
                                 f"{(ev.get('awayScore') or {}).get('display')}"] if status == "finished" else []),
        ))
    return out


def fetch(cfg) -> list[Event]:
    calendar = _calendar(cfg)
    today = datetime.now(timezone.utc).date()
    active = _active_today(calendar, today)
    if not active:
        return calendar                    # no PDC event today: no API calls
    try:
        return calendar + _matches(cfg, active, today)
    except Exception as exc:               # match-ups are a bonus; keep the calendar
        log.warning("darts match-ups failed: %s", str(exc).split("?")[0][:150])
        return calendar
