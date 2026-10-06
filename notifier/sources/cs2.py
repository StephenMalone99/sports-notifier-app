"""CS2 top-tier tournaments from PandaScore (free plan).

PandaScore keeps CS2 under the /csgo/ endpoints and tells CS:GO and CS2 apart
with filter[videogame_title]=cs-2. Tournaments carry a `tier` (s, a, b, c, d).
"""
from datetime import datetime

import requests

from ..keystore import get_secret
from ..models import Event

BASE = "https://api.pandascore.co/csgo"


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
    for t in raw:
        if str(t.get("tier") or "").lower() not in tiers or not t.get("begin_at"):
            continue
        serie = t.get("serie") or {}
        league = t.get("league") or {}
        key = serie.get("id") or t["id"]
        name = " ".join(
            x for x in [league.get("name"), serie.get("full_name") or serie.get("name")] if x
        ) or t.get("name", "CS2 tournament")
        e = series.setdefault(key, {
            "name": name, "begin": _dt(t["begin_at"]), "end": _dt(t.get("end_at")),
            "tier": t.get("tier"), "stages": [], "prize": t.get("prizepool"),
            "slug": serie.get("slug") or t.get("slug"),
        })
        e["begin"] = min(e["begin"], _dt(t["begin_at"]))
        if t.get("end_at"):
            end = _dt(t["end_at"])
            e["end"] = max(e["end"], end) if e["end"] else end
        e["stages"].append(t.get("name", ""))
        e["prize"] = e["prize"] or t.get("prizepool")

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
            tags=[f"tier-{str(e['tier']).lower()}"],
        ))
    return events
