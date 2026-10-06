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
        e["prize"] = e["prize"] or t.get("prizepool")

    if skipped:
        log.info("CS2 skipped (not top tier): %s",
                 "; ".join(f"{n} [{t.upper()}]" for n, t in list(skipped.items())[:20]))

    events = []
    for key, e in series.items():
        events.append(Event(
            id=f"cs2-{key}",
            sport="cs2",
            title=e["name"],
            start=e["begin"],
            end=e["end"],
            competition=f"Tier {str(e['tier']).upper()}",
            detail=" · ".join(x for x in [_prize(e["prize"]), ", ".join(s for s in e["stages"] if s)] if x),
            url="https://www.hltv.org/events",
            all_day=True,
            tags=[f"tier-{str(e['tier']).lower()}", f"serie-{key}"],
        ))

    serie_ids = {e["serie_id"]: e["name"] for e in series.values() if e["serie_id"]}
    if serie_ids:
        try:
            events.extend(_matches(headers, serie_ids, cfg))
        except Exception as exc:  # tournaments still show if match lookup fails
            log.warning("CS2 match lookup failed: %s", str(exc).split("?")[0][:200])
    return events


def _team(o):
    t = (o or {}).get("opponent") or {}
    return t.get("name") or t.get("acronym") or "TBD"


def _stream(m):
    streams = m.get("streams_list") or []
    for pick in (lambda s: s.get("main"), lambda s: s.get("language") == "en", lambda s: True):
        for st in streams:
            if pick(st) and st.get("raw_url"):
                return st["raw_url"]
    return "https://www.hltv.org/matches"


def _matches(headers, serie_ids: dict, cfg) -> list[Event]:
    """Individual matches (teams, time, best-of) for the tracked events."""
    days = cfg.get("match_days_ahead", 7)
    horizon = datetime.now(timezone.utc) + timedelta(days=days)
    raw = []
    for state in ("running", "upcoming"):
        r = requests.get(
            f"{BASE}/matches/{state}",
            headers=headers,
            params={"filter[serie_id]": ",".join(str(i) for i in serie_ids),
                    "per_page": 100, "sort": "begin_at"},
            timeout=20,
        )
        r.raise_for_status()
        raw.extend(r.json())

    events = []
    for m in raw:
        when = _dt(m.get("begin_at") or m.get("scheduled_at"))
        if not when or when > horizon:
            continue
        opp = m.get("opponents") or []
        a = _team(opp[0]) if len(opp) > 0 else "TBD"
        b = _team(opp[1]) if len(opp) > 1 else "TBD"
        stage = (m.get("tournament") or {}).get("name", "")
        bo = f"BO{m['number_of_games']}" if m.get("number_of_games") else ""
        live = ""
        if m.get("status") == "running" and m.get("results"):
            score = [str(r.get("score", 0)) for r in m["results"]]
            live = f"LIVE {'-'.join(score)}"
        events.append(Event(
            id=f"cs2m-{m['id']}",
            sport="cs2",
            title=f"{a} vs {b}",
            start=when,
            competition=serie_ids.get(m.get("serie_id"), "CS2"),
            detail=" · ".join(x for x in [bo, stage, live] if x),
            url=_stream(m),
            tags=["match", f"serie-{m.get('serie_id')}"],
        ))
    return events
