"""Results after matches (optional - turn off in config.yaml if you don't want spoilers).

Each function returns a list of alerts: (key, title, body, tags, click_url).
Only results that finished in the last `window_hours` are sent, once each.
"""
import logging
from datetime import datetime, timedelta, timezone

import requests

from .keystore import get_secret

log = logging.getLogger("notifier")


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


# ---------- Liverpool ----------
def liverpool(cfg, now, window_hours=12) -> list:
    out, seen_days = [], set()
    since = now - timedelta(hours=window_hours)
    token = get_secret("FOOTBALL_DATA_TOKEN")
    if token:
        r = requests.get(
            "https://api.football-data.org/v4/teams/64/matches",
            headers={"X-Auth-Token": token},
            params={"status": "FINISHED",
                    "dateFrom": (now - timedelta(days=2)).date().isoformat(),
                    "dateTo": now.date().isoformat()},
            timeout=20,
        )
        r.raise_for_status()
        for m in r.json().get("matches", []):
            ko = _dt(m["utcDate"])
            if not ko or ko + timedelta(hours=2) < since:
                continue
            ft = (m.get("score") or {}).get("fullTime") or {}
            h, a = ft.get("home"), ft.get("away")
            if h is None or a is None:
                continue
            home, away = m["homeTeam"]["name"], m["awayTeam"]["name"]
            lfc_home = m["homeTeam"]["id"] == 64
            us, them = (h, a) if lfc_home else (a, h)
            extra = ""
            dur = (m.get("score") or {}).get("duration")
            if dur == "EXTRA_TIME":
                extra = " (AET)"
            elif dur == "PENALTY_SHOOTOUT":
                p = (m.get("score") or {}).get("penalties") or {}
                extra = f" (pens {p.get('home')}-{p.get('away')})"
            outcome = "Win" if us > them else "Loss" if us < them else "Draw"
            seen_days.add(ko.date())
            out.append((
                f"res-lfc-{m['id']}",
                f"FT: {home} {h}-{a} {away}{extra}",
                f"{outcome} · {m['competition']['name']}",
                "soccer," + {"Win": "white_check_mark", "Loss": "x", "Draw": "heavy_minus_sign"}[outcome],
                "https://www.liverpoolfc.com/fixtures",
            ))
    # Cup games football-data doesn't cover
    try:
        r = requests.get("https://www.thesportsdb.com/api/v1/json/123/eventslast.php",
                         params={"id": 133602}, timeout=20)
        r.raise_for_status()
        for m in (r.json() or {}).get("results") or []:
            when = _dt((m.get("strTimestamp") or "") + ("" if "+" in (m.get("strTimestamp") or "") else "+00:00")) \
                if m.get("strTimestamp") else None
            if not when or when.date() in seen_days or when + timedelta(hours=2) < since:
                continue
            if m.get("intHomeScore") is None or m.get("intAwayScore") is None:
                continue
            out.append((
                f"res-lfc-tsdb-{m['idEvent']}",
                f"FT: {m.get('strHomeTeam')} {m['intHomeScore']}-{m['intAwayScore']} {m.get('strAwayTeam')}",
                m.get("strLeague") or "",
                "soccer",
                "https://www.liverpoolfc.com/fixtures",
            ))
    except Exception as exc:
        log.info("TheSportsDB results skipped: %s", str(exc)[:120])
    return out


# ---------- CS2 favourite teams ----------
def cs2(cfg, now, favs: dict, window_hours=6) -> list:
    token = get_secret("PANDASCORE_TOKEN")
    if not token or not favs:
        return []
    r = requests.get(
        "https://api.pandascore.co/csgo/matches/past",
        headers={"Authorization": f"Bearer {token}"},
        params={"filter[videogame_title]": "cs-2", "sort": "-end_at", "per_page": 100},
        timeout=20,
    )
    r.raise_for_status()
    since = now - timedelta(hours=window_hours)
    out = []
    for m in r.json():
        end = _dt(m.get("end_at"))
        if m.get("status") != "finished" or not end or end < since:
            continue
        teams = [((o or {}).get("opponent") or {}) for o in (m.get("opponents") or [])]
        if len(teams) != 2:
            continue

        def fav_name(t):
            for x in (t.get("name"), t.get("acronym")):
                if x and x.lower() in favs:
                    return favs[x.lower()]
            return None

        mine = [fav_name(t) for t in teams]
        if not any(mine):
            continue
        score = {r_.get("team_id"): r_.get("score", 0) for r_ in (m.get("results") or [])}
        a, b = teams
        sa, sb = score.get(a.get("id"), 0), score.get(b.get("id"), 0)
        winner_id = m.get("winner_id") or (m.get("winner") or {}).get("id")
        disp = [mine[0] or a.get("name", "?"), mine[1] or b.get("name", "?")]
        if winner_id == a.get("id"):
            title = f"{disp[0]} beat {disp[1]} {sa}-{sb}"
        elif winner_id == b.get("id"):
            title = f"{disp[1]} beat {disp[0]} {sb}-{sa}"
        else:
            title = f"{disp[0]} {sa}-{sb} {disp[1]}"
        league = (m.get("league") or {}).get("name", "")
        serie = (m.get("serie") or {}).get("full_name", "")
        stage = (m.get("tournament") or {}).get("name", "")
        out.append((
            f"res-cs2-{m['id']}",
            title,
            " · ".join(x for x in [f"{league} {serie}".strip(), stage] if x),
            "video_game,trophy",
            "https://www.hltv.org/results",
        ))
    return out


# ---------- F1 ----------
def f1(cfg, now, window_hours=36) -> list:
    out = []
    for kind, path in (("race", "results"), ("sprint", "sprint")):
        r = requests.get(f"https://api.jolpi.ca/ergast/f1/current/last/{path}.json", timeout=20)
        if r.status_code != 200:
            continue
        races = r.json()["MRData"]["RaceTable"]["Races"]
        if not races:
            continue
        race = races[0]
        rows = race.get("Results") or race.get("SprintResults") or []
        if not rows:
            continue
        when = _dt(f"{race['date']}T{race.get('time', '12:00:00Z')}")
        if kind == "sprint":
            s = race.get("Sprint") or {}
            when = _dt(f"{s.get('date', race['date'])}T{s.get('time', '12:00:00Z')}")
        if not when or when < now - timedelta(hours=window_hours):
            continue
        podium = [f"{x['position']}. {x['Driver'].get('givenName', '')} {x['Driver'].get('familyName', '')}"
                  f" ({x.get('Constructor', {}).get('name', '')})" for x in rows[:3]]
        label = "Sprint" if kind == "sprint" else "Race"
        out.append((
            f"res-f1-{race['season']}-{race['round']}-{kind}",
            f"{race['raceName']} {label} result",
            "\n".join(podium),
            "checkered_flag,trophy",
            race.get("url") or "https://www.formula1.com/en/results",
        ))
    return out
