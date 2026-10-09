"""Starting line-ups for Liverpool matches.

1st choice: SportsAPI Pro (official data; needs SPORTSAPIPRO_KEY; a few requests
            per match day). Line-ups appear once confirmed, ~30-60 min before kick-off.
Fallback:   ESPN's public (unofficial) data, no key.
Every failure is caught; the kick-off reminder still goes out without line-ups.
"""
import logging

import requests

from .keystore import get_secret
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


def _espn_lineup(match: Event) -> str | None:
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
        return teams
    except Exception as exc:
        log.warning("Line-ups lookup failed: %s", str(exc).split("?")[0][:200])
        return None


# ---------------- SportsAPI Pro (official) ----------------
SAP = "https://api.sportsapipro.com/v2/football/api"
_sap_match: dict[str, int] = {}          # our event id -> SportsAPI Pro match id (per run)


def _sap_get(key, path):
    r = requests.get(f"{SAP}{path}", headers={"x-api-key": key}, timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    j = r.json()
    return j.get("data", j) if isinstance(j, dict) else j


def _sap_find_match(key, match: Event, team_id: int) -> int | None:
    if match.id in _sap_match:
        return _sap_match[match.id]
    data = _sap_get(key, f"/teams/{team_id}/near-events") or {}
    if not data:   # id not recognised: look Liverpool up once and log the right id
        found = _sap_get(key, "/search?q=liverpool") or {}
        results = found.get("results", found) if isinstance(found, dict) else found
        for item in results if isinstance(results, list) else []:
            ent = item.get("entity", item)
            if (ent.get("name") or "").lower() == "liverpool" and "football" in str(ent.get("sport", "football")).lower():
                log.info("SportsAPI Pro: Liverpool team id is %s (set liverpool.sportsapipro_team_id)", ent.get("id"))
                data = _sap_get(key, f"/teams/{ent.get('id')}/near-events") or {}
                break
    for ev in (data.get("nextEvent"), data.get("previousEvent")):
        if ev and ev.get("startTimestamp") and abs(ev["startTimestamp"] - match.start.timestamp()) < 3 * 3600:
            _sap_match[match.id] = ev["id"]
            return ev["id"]
    return None


def _sap_lineup(match: Event, team_id: int) -> str | None:
    key = get_secret("SPORTSAPIPRO_KEY")
    if not key:
        return None
    mid = _sap_find_match(key, match, team_id)
    if not mid:
        log.info("Line-ups (SportsAPI Pro): match not found")
        return None
    data = _sap_get(key, f"/match/{mid}/lineups")
    if not data or not data.get("confirmed"):
        log.info("Line-ups (SportsAPI Pro): not confirmed yet")
        return None
    sides = []
    home_name, away_name = (match.title.split(" vs ") + ["", ""])[:2]
    for side, name in (("home", home_name), ("away", away_name)):
        t = data.get(side) or {}
        xi = [((p.get("player") or {}).get("shortName") or (p.get("player") or {}).get("name") or "?")
              for p in t.get("players", []) if not p.get("substitute")]
        if len(xi) >= 11:
            sides.append((name or side.title(), t.get("formation") or "", xi[:11]))
    if len(sides) < 2:
        return None
    sides.sort(key=lambda x: 0 if "liverpool" in x[0].lower() else 1)
    return sides


def fetch_lineups(match: Event, team_id: int = 44) -> list | None:
    """[(team, formation, [11 names]), ...] with Liverpool first, or None if not out yet."""
    try:
        got = _sap_lineup(match, team_id)
        if got:
            return got
    except Exception as exc:
        log.warning("Line-ups (SportsAPI Pro) failed: %s", str(exc).split("?")[0][:150])
    return _espn_lineup(match)


def fetch_lineup(match: Event, team_id: int = 44) -> str | None:
    """Plain-text version (kept for the dashboard / older callers)."""
    teams = fetch_lineups(match, team_id)
    if not teams:
        return None
    return "\n".join(f"{t}" + (f" ({f})" if f else "") + ": " + ", ".join(xi) for t, f, xi in teams)
