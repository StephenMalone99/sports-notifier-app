"""CS2 top-tier tournaments from PandaScore (free plan).

PandaScore keeps CS2 under the /csgo/ endpoints and tells CS:GO and CS2 apart
with filter[videogame_title]=cs-2. Tournaments carry a `tier` (s, a, b, c, d).
"""
import logging
from datetime import datetime, timedelta, timezone

import requests

from ..keystore import get_secret
from ..models import Event

BASE = "https://api.pandascore.co/csgo"
log = logging.getLogger("notifier")


def _dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _prize(p):
    """'1250000 United States Dollar' -> '$1,250,000 prize pool'."""
    if not p:
        return None
    amount, _, cur = str(p).partition(" ")
    if not amount.isdigit():
        return str(p)
    sym = {"United States Dollar": "$", "Euro": "€", "Pound Sterling": "£"}.get(cur, "")
    return f"{sym}{int(amount):,}{'' if sym else ' ' + cur} prize pool"


def fetch(cfg) -> list[Event]:
    token = get_secret("PANDASCORE_TOKEN")
    if not token:
        raise RuntimeError("PANDASCORE_TOKEN not set — run: python -m notifier.set_keys")

    tiers = {t.lower() for t in cfg.get("tiers", ["s"])}
    # PandaScore's tier labels don't always match what fans call tier 1, so
    # these events are kept whatever tier PandaScore gives them.
    include = [k.lower() for k in cfg.get("always_include", [])]
    exclude = [k.lower() for k in cfg.get("exclude", [])]
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    raw = []
    for state in ("running", "upcoming"):
        r = requests.get(
            f"{BASE}/tournaments/{state}",
            headers=headers,
            params={"filter[videogame_title]": "cs-2", "per_page": 100, "sort": "begin_at"},
            timeout=20,
        )
        r.raise_for_status()
        raw.extend(r.json())

    # A PandaScore "tournament" is often one stage (Group A, Playoffs…) of a bigger
    # event (the "serie"). Merge stages so you see one entry per event.
    series: dict[int, dict] = {}
    skipped = {}
    for t in raw:
        if not t.get("begin_at"):
            continue
        serie = t.get("serie") or {}
        league = t.get("league") or {}
        key = serie.get("id") or t["id"]
        name = " ".join(
            x for x in [league.get("name"), serie.get("full_name") or serie.get("name")] if x
        ) or t.get("name", "CS2 tournament")
        tier = str(t.get("tier") or "?").lower()
        lname = name.lower()
        wanted = (tier in tiers or any(k in lname for k in include)) and not any(
            k in lname for k in exclude)
        if not wanted:
            skipped[name] = tier
            continue
        e = series.setdefault(key, {
            "name": name, "begin": _dt(t["begin_at"]), "end": _dt(t.get("end_at")),
            "tier": t.get("tier"), "stages": [], "prize": t.get("prizepool"),
            "slug": serie.get("slug") or t.get("slug"),
            "serie_id": serie.get("id"),
        })
        e["begin"] = min(e["begin"], _dt(t["begin_at"]))
        if t.get("end_at"):
            end = _dt(t["end_at"])
            e["end"] = max(e["end"], end) if e["end"] else end
        e["stages"].append(t.get("name", ""))
        e.setdefault("teams", set()).update(
            x.get("name", "") for x in (t.get("teams") or []) if isinstance(x, dict))
        e["prize"] = e["prize"] or t.get("prizepool")

    if skipped:
        log.info("CS2 skipped (not top tier): %s",
                 "; ".join(f"{n} [{t.upper()}]" for n, t in list(skipped.items())[:20]))

    favs = _fav_aliases(cfg)
    events = []
    for key, e in series.items():
        mine = sorted({favs[n.lower()] for n in e.get("teams", ()) if n.lower() in favs})
        detail = " · ".join(x for x in [
            _prize(e["prize"]), ", ".join(s for s in e["stages"] if s),
            f"Your teams: {', '.join(mine)}" if mine else ""] if x)
        events.append(Event(
            id=f"cs2-{key}",
            sport="cs2",
            title=e["name"],
            start=e["begin"],
            end=e["end"],
            competition=f"Tier {str(e['tier']).upper()}",
            detail=detail,
            url="https://www.hltv.org/events",
            all_day=True,
            tags=[f"tier-{str(e['tier']).lower()}", f"serie-{key}"] + (["fav"] if mine else []),
        ))

    serie_ids = {e["serie_id"]: e["name"] for e in series.values() if e["serie_id"]}
    seen = set()
    if serie_ids:
        try:
            for ev in _matches(headers, serie_ids, cfg, favs):
                seen.add(ev.id)
                events.append(ev)
        except Exception as exc:  # tournaments still show if match lookup fails
            log.warning("CS2 match lookup failed: %s", str(exc).split("?")[0][:200])
    if favs:
        try:
            extra = [ev for ev in _fav_matches(headers, cfg, favs) if ev.id not in seen]
            events.extend(extra)
            log.info("CS2 favourite-team matches found: %d",
                     sum(1 for ev in events if "fav" in ev.tags and "match" in ev.tags))
        except Exception as exc:
            log.warning("CS2 favourite lookup failed: %s", str(exc).split("?")[0][:200])
    return events


def _fav_aliases(cfg) -> dict:
    """{'natus vincere': 'NAVI', 'navi': 'NAVI', ...} from config favourite_teams."""
    out = {}
    for display, aliases in (cfg.get("favourite_teams") or {}).items():
        for a in [display] + list(aliases or []):
            out[str(a).lower()] = display
    return out


def _team(o):
    t = (o or {}).get("opponent") or {}
    return t.get("name") or t.get("acronym") or "TBD"


def _stream_label(url: str) -> str:
    """'https://www.twitch.tv/eslcs' -> 'twitch.tv/eslcs'."""
    if not url or "hltv.org" in url:
        return ""
    u = url.split("://", 1)[-1].removeprefix("www.").removeprefix("m.")
    u = u.split("?")[0].rstrip("/")
    if "youtube.com" in u and "/watch" in u:
        return "YouTube"
    return u


def _stream(m):
    streams = m.get("streams_list") or []
    for pick in (lambda s: s.get("main"), lambda s: s.get("language") == "en", lambda s: True):
        for st in streams:
            if pick(st) and st.get("raw_url"):
                return st["raw_url"]
    return "https://www.hltv.org/matches"


def _match_event(m, competition: str, favs: dict) -> Event | None:
    when = _dt(m.get("begin_at") or m.get("scheduled_at"))
    if not when:
        return None
    teams = [((o or {}).get("opponent") or {}) for o in (m.get("opponents") or [])]
    names = [t.get("name") or t.get("acronym") or "TBD" for t in teams] + ["TBD", "TBD"]
    mine = sorted({favs[x.lower()] for t in teams for x in (t.get("name"), t.get("acronym"))
                   if x and x.lower() in favs})
    stage = (m.get("tournament") or {}).get("name", "")
    bo = f"BO{m['number_of_games']}" if m.get("number_of_games") else ""
    live = ""
    if m.get("status") == "running" and m.get("results"):
        live = "LIVE " + "-".join(str(r.get("score", 0)) for r in m["results"])
    return Event(
        id=f"cs2m-{m['id']}",
        sport="cs2",
        title=f"{names[0]} vs {names[1]}",
        start=when,
        competition=competition,
        detail=" · ".join(x for x in [bo, stage, live] if x),
        url=_stream(m),
        tags=["match", f"serie-{m.get('serie_id')}"]
             + ([f"watch:{_stream_label(_stream(m))}"] if _stream_label(_stream(m)) else [])
             + (["fav"] + [f"team:{t}" for t in mine] if mine else [])
             + (["live"] if m.get("status") == "running" else []),
    )


def _get_matches(headers, params, pages=1) -> list:
    raw = []
    for state in ("running", "upcoming"):
        for page in range(1, (pages if state == "upcoming" else 1) + 1):
            r = requests.get(f"{BASE}/matches/{state}", headers=headers, timeout=20,
                             params={**params, "per_page": 100, "page": page, "sort": "begin_at"})
            r.raise_for_status()
            batch = r.json()
            raw.extend(batch)
            if len(batch) < 100:
                break
    return raw


def _matches(headers, serie_ids: dict, cfg, favs: dict) -> list[Event]:
    """Every match (teams, time, best-of) in the tracked top-tier events."""
    horizon = datetime.now(timezone.utc) + timedelta(days=cfg.get("match_days_ahead", 7))
    raw = _get_matches(headers, {"filter[serie_id]": ",".join(str(i) for i in serie_ids)})
    out = []
    for m in raw:
        ev = _match_event(m, serie_ids.get(m.get("serie_id"), "CS2"), favs)
        if ev and ev.start <= horizon:
            out.append(ev)
    return out


def _fav_matches(headers, cfg, favs: dict) -> list[Event]:
    """Favourite teams' matches at ANY event, not just the tracked ones."""
    horizon = datetime.now(timezone.utc) + timedelta(days=cfg.get("favourite_days_ahead", 14))
    raw = _get_matches(headers, {"filter[videogame_title]": "cs-2"}, pages=3)
    out = []
    for m in raw:
        league = (m.get("league") or {}).get("name", "")
        serie = (m.get("serie") or {}).get("full_name") or (m.get("serie") or {}).get("name") or ""
        ev = _match_event(m, " ".join(x for x in [league, serie] if x) or "CS2", favs)
        if ev and "fav" in ev.tags and ev.start <= horizon:
            out.append(ev)
    return out
