"""Liverpool FC fixtures.

Primary: football-data.org (free tier: Premier League + Champions League).
Backup:  TheSportsDB free API, which also lists FA Cup / League Cup games.
Fixtures from both are merged; duplicates (same day) are dropped.
"""
from datetime import datetime, timezone

import requests

from ..keystore import get_secret
from ..models import Event

FD_TEAM_ID = 64          # Liverpool on football-data.org
TSDB_TEAM_ID = 133602    # Liverpool on TheSportsDB
TSDB_FREE_KEY = "123"    # TheSportsDB's public test key (not a secret)


def _fd(cfg) -> list[Event]:
    token = get_secret("FOOTBALL_DATA_TOKEN")
    if not token:
        raise RuntimeError("FOOTBALL_DATA_TOKEN not set — run: python -m notifier.set_keys")
    r = requests.get(
        f"https://api.football-data.org/v4/teams/{FD_TEAM_ID}/matches",
        headers={"X-Auth-Token": token},
        params={"status": "SCHEDULED,TIMED,IN_PLAY,PAUSED"},
        timeout=20,
    )
    r.raise_for_status()
    events = []
    for m in r.json().get("matches", []):
        home, away = m["homeTeam"]["name"], m["awayTeam"]["name"]
        lfc_home = m["homeTeam"]["id"] == FD_TEAM_ID
        opponent = away if lfc_home else home
        events.append(Event(
            id=f"lfc-fd-{m['id']}",
            sport="liverpool",
            title=f"Liverpool vs {opponent}" if lfc_home else f"{opponent} vs Liverpool",
            start=datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")),
            competition=m["competition"]["name"],
            detail=" · ".join(x for x in [
                "Home" if lfc_home else "Away",
                m.get("venue") or ("Anfield" if lfc_home else ""),
                m.get("stage", "").replace("_", " ").title()
                if m.get("stage") not in (None, "REGULAR_SEASON") else "",
                f"Matchday {m['matchday']}" if m.get("matchday") else "",
            ] if x),
            url="https://www.liverpoolfc.com/fixtures",
            tags=["home" if lfc_home else "away"],
        ))
    return events


def _tsdb(cfg) -> list[Event]:
    r = requests.get(
        f"https://www.thesportsdb.com/api/v1/json/{TSDB_FREE_KEY}/eventsnext.php",
        params={"id": TSDB_TEAM_ID}, timeout=20,
    )
    r.raise_for_status()
    events = []
    for m in (r.json() or {}).get("events") or []:
        ts = m.get("strTimestamp")
        if ts:
            start = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        elif m.get("dateEvent"):
            start = datetime.fromisoformat(m["dateEvent"] + "T12:00:00+00:00")
        else:
            continue
        lfc_home = str(m.get("idHomeTeam")) == str(TSDB_TEAM_ID)
        events.append(Event(
            id=f"lfc-tsdb-{m['idEvent']}",
            sport="liverpool",
            title=m.get("strEvent") or "Liverpool match",
            start=start,
            competition=m.get("strLeague") or "",
            detail="Home · Anfield" if lfc_home else "Away",
            url="https://www.liverpoolfc.com/fixtures",
            tags=["home" if lfc_home else "away"],
        ))
    return events


def fetch(cfg) -> list[Event]:
    events, errors = [], []
    for source in (_fd, _tsdb):
        try:
            got = source(cfg)
        except Exception as exc:  # one source failing shouldn't hide the other
            errors.append(f"{source.__name__}: {exc}")
            continue
        seen_days = {e.start.date() for e in events}
        events.extend(e for e in got if e.start.date() not in seen_days)
    if not events and errors:
        raise RuntimeError("; ".join(errors))
    return events
