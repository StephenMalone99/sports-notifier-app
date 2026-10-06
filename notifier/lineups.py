"""Starting line-ups for Liverpool matches, from ESPN's public (unofficial) data.

No key needed. Line-ups usually appear 60-75 minutes before kick-off.
This is an unofficial source, so every failure is caught and the kick-off
reminder simply goes out without line-ups.
"""
import logging

import requests

from .models import Event

log = logging.getLogger("notifier")
BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
LIVERPOOL_ESPN_ID = "364"

# competition name (from football-data / TheSportsDB) -> ESPN league slug
LEAGUES = [
    ("premier league", "eng.1"),
    ("champions league", "uefa.champions"),
    ("europa league", "uefa.europa"),
    ("conference league", "uefa.europa.conf"),
    ("fa cup", "eng.fa"),
    ("league cup", "eng.league_cup"),
    ("efl cup", "eng.league_cup"),
    ("carabao", "eng.league_cup"),
    ("community shield", "eng.charity"),
]


def _slugs(competition: str) -> list[str]:
    c = competition.lower()
    hits = [slug for key, slug in LEAGUES if key in c]
    return hits or ["eng.1", "uefa.champions", "eng.league_cup", "eng.fa", "uefa.europa"]


def _find_event_id(match: Event) -> tuple[str, str] | None:
    day = match.start.strftime("%Y%m%d")
    for slug in _slugs(match.competition):
        r = requests.get(f"{BASE}/{slug}/scoreboard", params={"dates": day}, timeout=15)
        if r.status_code != 200:
            continue
        for ev in r.json().get("events", []):
            comps = (ev.get("competitions") or [{}])[0].get("competitors", [])
            if any(str((c.get("team") or {}).get("id")) == LIVERPOOL_ESPN_ID
                   or "liverpool" == ((c.get("team") or {}).get("displayName") or "").lower()
                   for c in comps):
                return slug, str(ev["id"])
    return None


def _xi(roster: dict) -> tuple[str, list[str]]:
    starters = [p for p in roster.get("roster", []) if p.get("starter")]
    names = []
    for p in starters:
        a = p.get("athlete") or {}
        name = a.get("shortName") or a.get("displayName") or "?"
        names.append(name)
    return roster.get("formation") or "", names


def fetch_lineup(match: Event) -> str | None:
    """Plain-text line-ups for both teams, or None if not announced / unavailable."""
    try:
        found = _find_event_id(match)
        if not found:
            log.info("Line-ups: match not found on ESPN yet")
            return None
        slug, event_id = found
        r = requests.get(f"{BASE}/{slug}/summary", params={"event": event_id}, timeout=15)
        r.raise_for_status()
        rosters = r.json().get("rosters") or []
        teams = []
        for ro in rosters:
            formation, xi = _xi(ro)
            if len(xi) >= 11:
                team = (ro.get("team") or {}).get("displayName") or "?"
                teams.append((team, formation, xi))
        if not teams:
            log.info("Line-ups: not announced yet")
            return None
        # Liverpool first
        teams.sort(key=lambda t: 0 if "liverpool" in t[0].lower() else 1)
        lines = []
        for team, formation, xi in teams:
            head = f"{team.upper()}" + (f" ({formation})" if formation else "")
            lines.append(head + "\n" + ", ".join(xi))
        return "\n\n".join(lines)
    except Exception as exc:
        log.warning("Line-ups lookup failed: %s", str(exc).split("?")[0][:200])
        return None
