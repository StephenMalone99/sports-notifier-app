"""Extra detail for alerts: recent form and league positions.

Only called when an alert is actually going out (a reminder or a result), so it
costs a handful of requests per match, not per run. Every lookup is cached for
the run and fails quietly - an alert never waits on, or breaks because of, these.
"""
import logging

import requests

from .keystore import get_secret

log = logging.getLogger("notifier")
_cache: dict = {}


def cs2_form(team_id, n: int = 5) -> str:
    """'WWLWW' (oldest -> newest) from a CS2 team's last n finished matches, or ''."""
    key = ("form", team_id)
    if key in _cache:
        return _cache[key]
    out = ""
    token = get_secret("PANDASCORE_TOKEN")
    if token and team_id:
        try:
            r = requests.get("https://api.pandascore.co/csgo/matches/past", timeout=15,
                             headers={"Authorization": f"Bearer {token}"},
                             params={"filter[opponent_id]": team_id, "sort": "-begin_at",
                                     "per_page": n * 2})
            r.raise_for_status()
            done = [m for m in r.json() if m.get("status") == "finished" and m.get("winner_id")][:n]
            out = "".join("W" if m["winner_id"] == int(team_id) else "L" for m in reversed(done))
        except Exception as exc:
            log.info("CS2 form lookup skipped: %s", str(exc).split("?")[0][:100])
    _cache[key] = out
    return out


def fd_table(code: str) -> dict:
    """{team_id: (position, points)} for a football-data competition (PL, CL...), or {}."""
    key = ("table", code)
    if key in _cache:
        return _cache[key]
    out = {}
    token = get_secret("FOOTBALL_DATA_TOKEN")
    if token and code:
        try:
            r = requests.get(f"https://api.football-data.org/v4/competitions/{code}/standings",
                             headers={"X-Auth-Token": token}, timeout=15)
            r.raise_for_status()
            for st in r.json().get("standings", []):
                if st.get("type", "TOTAL") != "TOTAL":
                    continue
                for row in st.get("table", []):
                    out[row["team"]["id"]] = (row["position"], row["points"])
        except Exception as exc:
            log.info("Table lookup (%s) skipped: %s", code, str(exc).split("?")[0][:100])
    _cache[key] = out
    return out
