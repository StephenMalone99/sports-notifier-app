"""Results after matches (optional - turn off in config.yaml if you don't want spoilers).

Each function returns a list of `Alert`s (see format.py). Only results from the
last few hours are returned; notify.py sends each one once.
"""
import logging
from datetime import datetime, timedelta, timezone

import requests

from . import enrich
from .format import (HIGH, NORMAL, Alert, dash, join, ordinal, short_comp, short_round,
                     short_team, surname)
from .keystore import get_secret

log = logging.getLogger("notifier")
BBC_LFC = "https://www.bbc.co.uk/sport/football/teams/liverpool/scores-fixtures"


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


# ---------- Liverpool ----------
def liverpool(cfg, now, state=None, window_hours=12) -> list:
    state = state if state is not None else {}
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
            sc = m.get("score") or {}
            ft, ht = sc.get("fullTime") or {}, sc.get("halfTime") or {}
            h, a = ft.get("home"), ft.get("away")
            if h is None or a is None:
                continue
            home = short_team(m["homeTeam"].get("shortName") or m["homeTeam"]["name"])
            away = short_team(m["awayTeam"].get("shortName") or m["awayTeam"]["name"])
            lfc_home = m["homeTeam"]["id"] == 64
            us, them = (h, a) if lfc_home else (a, h)
            extra = ""
            if sc.get("duration") == "EXTRA_TIME":
                extra = " (aet)"
            elif sc.get("duration") == "PENALTY_SHOOTOUT":
                p = sc.get("penalties") or {}
                extra = f" ({dash(p.get('home'), p.get('away'))} pens)"
            outcome = "W" if us > them else "L" if us < them else "D"
            comp = m.get("competition") or {}
            code = comp.get("code", "")
            md = f"MD{m['matchday']}" if m.get("matchday") else ""
            ht_line = f"HT {dash(ht.get('home'), ht.get('away'))}" if ht.get("home") is not None else ""

            # Where Liverpool stand now (and the move since the last result)
            table_line = ""
            table = enrich.fd_table(code) if code in ("PL", "CL") else {}
            if 64 in table:
                pos, pts = table[64]
                prev = state.get(f"lfcpos-{code}", "").split("|")[0]
                move = ""
                if prev.isdigit() and int(prev) != pos:
                    move = f" (▲{int(prev) - pos})" if int(prev) > pos else f" (▼{pos - int(prev)})"
                table_line = f"Liverpool {'go' if move else 'stay'} {ordinal(pos)}{move} · {pts} pts"
                state[f"lfcpos-{code}"] = f"{pos}|{now.isoformat()}"

            seen_days.add(ko.date())
            out.append(Alert(
                key=f"res-lfc-{m['id']}",
                title=f"FT: {home} {dash(h, a)} {away}{extra}",
                lines=[join(ht_line, short_comp(comp.get("name", "")), md), table_line],
                emoji={"W": "white_check_mark", "L": "x", "D": "heavy_minus_sign"}[outcome],
                click=BBC_LFC, priority=NORMAL, actions=[("Match report", BBC_LFC)],
            ))
    # Cup games football-data doesn't cover
    try:
        r = requests.get("https://www.thesportsdb.com/api/v1/json/123/eventslast.php",
                         params={"id": 133602}, timeout=20)
        r.raise_for_status()
        for m in (r.json() or {}).get("results") or []:
            ts = m.get("strTimestamp") or ""
            when = _dt(ts + ("" if "+" in ts else "+00:00")) if ts else None
            if not when or when.date() in seen_days or when + timedelta(hours=2) < since:
                continue
            if m.get("intHomeScore") is None or m.get("intAwayScore") is None:
                continue
            out.append(Alert(
                key=f"res-lfc-tsdb-{m['idEvent']}",
                title=f"FT: {short_team(m.get('strHomeTeam'))} {dash(m['intHomeScore'], m['intAwayScore'])}"
                      f" {short_team(m.get('strAwayTeam'))}",
                lines=[short_comp(m.get("strLeague") or "")],
                emoji="soccer", click=BBC_LFC, actions=[("Match report", BBC_LFC)],
            ))
    except Exception as exc:
        log.info("TheSportsDB results skipped: %s", str(exc)[:120])
    return out


# ---------- CS2 favourite teams ----------
def _next_match(events, display: str, now, tz) -> str:
    """'Next: Sat 15:00 vs FaZe' for a favourite team, from the events already fetched."""
    me = short_team(display)
    for e in sorted(events or [], key=lambda e: e.start):
        if e.start > now and "match" in e.tags and f"team:{display}" in e.tags:
            names = e.title.split(" vs ")
            opp = next((n for n in names if n != me), "TBD")
            when = e.start.astimezone(tz) if tz else e.start
            return f"Next: {when:%a %H:%M} vs {opp}"
    return ""


def _maps(m, ids_to_name) -> str:
    """'Mirage Falcons · Inferno NAVI · Nuke Falcons' (map names if the plan includes them)."""
    out = []
    for g in sorted(m.get("games") or [], key=lambda g: g.get("position") or 0):
        win = ((g.get("winner") or {}).get("id"))
        if not win or g.get("status") not in (None, "finished"):
            continue
        name = ((g.get("map") or {}).get("name")) or f"Map {g.get('position', len(out) + 1)}"
        out.append(f"{name} {ids_to_name.get(win, '?')}")
    return " · ".join(out)


def _cs2_alert(m, favs, events=(), now=None, tz=None):
    """Alert for a finished match involving a favourite, else None."""
    if m.get("status") != "finished":
        return None
    teams = [((o or {}).get("opponent") or {}) for o in (m.get("opponents") or [])]
    if len(teams) != 2:
        return None

    def fav_name(t):
        for x in (t.get("name"), t.get("acronym")):
            if x and x.lower() in favs:
                return favs[x.lower()]
        return None

    mine = [fav_name(t) for t in teams]
    if not any(mine):
        return None
    score = {r_.get("team_id"): r_.get("score", 0) for r_ in (m.get("results") or [])}
    a, b = teams
    na, nb = short_team(a.get("name") or "?"), short_team(b.get("name") or "?")
    sa, sb = score.get(a.get("id"), 0), score.get(b.get("id"), 0)
    winner_id = m.get("winner_id") or (m.get("winner") or {}).get("id")
    if winner_id == a.get("id"):
        title, won = f"{na} beat {nb} {dash(sa, sb)}", mine[0]
    elif winner_id == b.get("id"):
        title, won = f"{nb} beat {na} {dash(sb, sa)}", mine[1]
    else:
        title, won = f"{na} {dash(sa, sb)} {nb}", None
    emoji = "white_check_mark" if won else ("x" if winner_id else "video_game")

    league = (m.get("league") or {}).get("name", "")
    serie = (m.get("serie") or {}).get("full_name", "")
    rnd = (m.get("name") or "").split(":")[0].strip() if ":" in (m.get("name") or "") else ""
    stage = rnd or (m.get("tournament") or {}).get("name", "")
    nxt = ""
    if now is not None:
        for fav in [x for x in mine if x]:
            nxt = _next_match(events, fav, now, tz)
            if nxt:
                break
    return Alert(
        key=f"res-cs2-{m['id']}",
        title=title,
        lines=[_maps(m, {a.get("id"): na, b.get("id"): nb}),
               join(short_comp(f"{league} {serie}".strip()), stage),
               nxt],
        emoji=emoji, click="https://www.hltv.org/results", priority=NORMAL,
        actions=[("HLTV results", "https://www.hltv.org/results")],
    )


def cs2(cfg, now, favs: dict, window_hours=6, watch_ids=(), events=(), tz=None) -> list:
    """Favourite-team results.

    1) Every favourite match we reminded about (watch_ids) is looked up by id
       until PandaScore marks it finished - delayed matches are often marked
       finished late and drop out of the 'recent results' list.
    2) The recent results list catches anything else.
    """
    token = get_secret("PANDASCORE_TOKEN")
    if not token or not favs:
        return []
    headers = {"Authorization": f"Bearer {token}"}
    out, seen = [], set()

    def add(m):
        alert = _cs2_alert(m, favs, events, now, tz)
        if alert and alert.key not in seen:
            out.append(alert)
            seen.add(alert.key)

    ids = list(dict.fromkeys(watch_ids))[:50]
    if ids:
        # The free plan can't fetch /matches/{id}, but the past list filtered by id works
        try:
            r = requests.get("https://api.pandascore.co/csgo/matches/past", headers=headers, timeout=20,
                             params={"filter[id]": ",".join(ids), "per_page": 100})
            r.raise_for_status()
            found = {str(m["id"]): m for m in r.json()}
        except Exception as exc:
            log.info("CS2 watched-match lookup failed: %s", str(exc).split("?")[0][:100])
            found = {}
        for mid in ids:
            m = found.get(mid)
            if not m:
                log.info("CS2 watched match %s: not finished yet", mid)
                continue
            names = " vs ".join(((o or {}).get("opponent") or {}).get("name", "?")
                                for o in m.get("opponents") or [])
            log.info("CS2 watched match %s (%s): %s", mid, names, m.get("status"))
            add(m)

    since = now - timedelta(hours=window_hours)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    r = requests.get(
        "https://api.pandascore.co/csgo/matches/past",
        headers=headers,
        params={"filter[videogame_title]": "cs-2", "sort": "-begin_at", "per_page": 100,
                "range[begin_at]": f"{(since - timedelta(hours=6)).strftime(fmt)},{now.strftime(fmt)}"},
        timeout=20,
    )
    r.raise_for_status()
    past = r.json()
    for m in past:
        end = _dt(m.get("end_at")) or _dt(m.get("modified_at")) or _dt(m.get("begin_at"))
        if end and end >= since:
            add(m)
    log.info("CS2 results: %d watched, %d recent matches checked, %d favourite-team results",
             len(watch_ids), len(past), len(out))
    return out


# ---------- F1 ----------
F1_TIMING = "https://www.formula1.com/en/timing/f1-live"
F1_RESULTS = "https://www.formula1.com/en/results"


def _secs(t: str):
    """'1:29.525' -> 89.525"""
    try:
        m, _, s = (t or "").rpartition(":")
        return (int(m) * 60 if m else 0) + float(s)
    except ValueError:
        return None


def _f1_get(path):
    r = requests.get(f"https://api.jolpi.ca/ergast/f1/current/{path}.json", timeout=20)
    return r.json()["MRData"] if r.status_code == 200 else None


def _when(d, fallback_date=None):
    if not d and not fallback_date:
        return None
    date = (d or {}).get("date") or fallback_date
    t = ((d or {}).get("time") or "12:00:00Z").replace("Z", "+00:00")
    return datetime.fromisoformat(f"{date}T{t}" + ("" if "+" in t else "+00:00"))


def f1(cfg, now, tz=None, window_hours=36) -> list:
    out = []
    tv = (cfg.get("f1") or {}).get("tv", "")
    gp = lambda race: short_comp(race["raceName"])

    # Qualifying: pole + top 3 with gaps, and when the race is
    q = _f1_get("last/qualifying")
    races = (q or {}).get("RaceTable", {}).get("Races", [])
    if races and races[0].get("QualifyingResults"):
        race = races[0]
        when = _when(race.get("Qualifying"), race.get("date"))
        if when and now - timedelta(hours=window_hours) <= when <= now:
            rows = race["QualifyingResults"][:3]
            best = [_secs(x.get("Q3") or x.get("Q2") or x.get("Q1")) for x in rows]
            parts = []
            for i, x in enumerate(rows):
                gap = f" +{best[i] - best[0]:.3f}" if i and best[i] and best[0] else ""
                parts.append(f"{x['position']} {x['Driver'].get('familyName', '')}{gap}")
            race_at = _when({"date": race.get("date"), "time": race.get("time")})
            race_local = (race_at.astimezone(tz) if tz else race_at) if race_at else None
            race_line = join(f"Race {race_local:%a %H:%M}" if race_local else "", tv)
            out.append(Alert(
                key=f"res-f1-{race['season']}-{race['round']}-quali",
                title=f"{gp(race)} · Pole: {rows[0]['Driver'].get('familyName', '')}",
                lines=[" · ".join(parts), race_line],
                emoji="checkered_flag", click=F1_RESULTS, actions=[("Results", F1_RESULTS)],
            ))

    # Sprint and race: winner, podium, fastest lap, championship top 3
    standings = None
    for kind, path in (("sprint", "last/sprint"), ("race", "last/results")):
        data = _f1_get(path)
        races = (data or {}).get("RaceTable", {}).get("Races", [])
        if not races:
            continue
        race = races[0]
        rows = race.get("Results") or race.get("SprintResults") or []
        if not rows:
            continue
        when = _when(race.get("Sprint") if kind == "sprint" else {"date": race.get("date"), "time": race.get("time")})
        if not when or not (now - timedelta(hours=window_hours) <= when <= now):
            continue
        name = lambda x: x["Driver"].get("familyName", "")
        lines = [" · ".join(f"{x['position']} {name(x)}" for x in rows[1:3])]
        if kind == "race":
            fl = next((x for x in rows if (x.get("FastestLap") or {}).get("rank") == "1"), None)
            if fl:
                lines.append(f"Fastest lap: {name(fl)}")
            if standings is None:
                st = _f1_get("driverStandings")
                lists = (st or {}).get("StandingsTable", {}).get("StandingsLists", [])
                standings = lists[0]["DriverStandings"][:3] if lists else []
            if standings:
                lines.append("Standings: " + " · ".join(
                    f"{d['Driver'].get('familyName', '')} {d['points']}" for d in standings))
        label = "Sprint: " if kind == "sprint" else ": "
        out.append(Alert(
            key=f"res-f1-{race['season']}-{race['round']}-{kind}",
            title=f"{gp(race)}{label}{name(rows[0])} wins",
            lines=lines, emoji="checkered_flag", click=F1_RESULTS,
            actions=[("Results", race.get("url") or F1_RESULTS)],
        ))
    return out


# ---------- Darts (with match stats from SportsAPI Pro) ----------
STAT_KEYS = [  # (label, words that identify the stat in the API's statistic names)
    ("Avg", ("average",)),
    ("180s", ("180",)),
    ("CO", ("checkout", "%")),
]


def _darts_stats(key: str, match_id: str) -> str:
    r = requests.get(f"https://api.sportsapipro.com/v2/darts/api/match/{match_id}/statistics",
                     headers={"x-api-key": key}, timeout=20)
    if r.status_code != 200:
        return ""
    data = r.json()
    data = data.get("data", data) if isinstance(data, dict) else data
    items = []

    def walk(x):   # collect every {name, home, away} item, whatever the nesting
        if isinstance(x, dict):
            if "name" in x and "home" in x and "away" in x:
                items.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data)
    out = []
    for label, words in STAT_KEYS:
        for it in items:
            name = str(it["name"]).lower()
            if all(w in name for w in words) and not (label == "CO" and "highest" in name) \
                    and not (label == "Avg" and "first" in name):
                h, a = str(it["home"]), str(it["away"])
                if label == "CO":
                    h, a = (v if v.endswith("%") else v + "%" for v in (h, a))
                out.append(f"{label} {h} v {a}")
                break
    return " · ".join(out)


def darts(cfg, now, events, window_hours=6) -> list:
    """Finished darts matches involving your chosen players (or any final/semi-final)."""
    key = get_secret("SPORTSAPIPRO_KEY")
    dc = cfg.get("darts", {})
    players = [p.lower() for p in dc.get("results_players", [])]
    out = []
    for e in events:
        if e.sport != "darts" or "finished" not in e.tags \
                or not (now - timedelta(hours=window_hours) <= e.start <= now):
            continue
        rnd = next((t[6:] for t in e.tags if t.startswith("round:")), "")
        big_round = any(w in rnd.lower() for w in ("final", "semi"))
        if not big_round and players and not any(p.split()[-1] in e.title.lower() for p in players):
            continue
        score = next((t[6:] for t in e.tags if t.startswith("score:")), "")
        home, away = (e.title.split(" vs ") + ["", ""])[:2]
        hs, _, as_ = score.partition("-")
        try:
            hw = int(hs) > int(as_)
            title = (f"{surname(home)} beat {surname(away)} {dash(hs, as_)}" if hw
                     else f"{surname(away)} beat {surname(home)} {dash(as_, hs)}")
            stats_first_home = hw
        except ValueError:
            title, stats_first_home = f"{surname(home)} {score} {surname(away)}", True
        mid = next((t[4:] for t in e.tags if t.startswith("sap:")), "")
        stats = ""
        if key and mid and dc.get("stats", True):
            try:
                stats = _darts_stats(key, mid)
                if stats and not stats_first_home:   # winner's numbers first, like the title
                    stats = " · ".join(
                        f"{p.split(' ')[0]} {p.split(' v ')[1]} v {p.split(' ', 1)[1].split(' v ')[0]}"
                        for p in stats.split(" · "))
            except Exception as exc:
                log.info("darts stats skipped: %s", str(exc)[:100])
        out.append(Alert(
            key=f"res-darts-{mid or e.id}",
            title=title,
            lines=[join(short_comp(e.competition), short_round(rnd)), stats],
            emoji="dart", click=e.url, actions=[("PDC", e.url)] if e.url else [],
        ))
    return out
