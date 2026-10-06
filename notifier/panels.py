"""'At a glance' panels for the dashboard: standings and recent form.

Only the dashboard uses these (the hourly alerts don't), so they cost a
handful of extra API calls every few hours. Each panel fails on its own:
if one source is down, the others still show.
"""
import logging
from datetime import datetime, timedelta, timezone

import requests

from .keystore import get_secret

log = logging.getLogger("notifier")
LFC = 64
_team_ids: dict[str, int] = {}   # PandaScore team ids, looked up once per run


def _short(name: str) -> str:
    for suffix in (" FC", " AFC", " CF", " SK", " KV"):
        name = name.removesuffix(suffix)
    return name


# ---------------- Liverpool ----------------
def liverpool(cfg) -> dict:
    token = get_secret("FOOTBALL_DATA_TOKEN")
    if not token:
        raise RuntimeError("football-data key not set")
    h = {"X-Auth-Token": token}
    now = datetime.now(timezone.utc)

    r = requests.get(f"https://api.football-data.org/v4/teams/{LFC}/matches", headers=h, timeout=20,
                     params={"status": "FINISHED",
                             "dateFrom": (now - timedelta(days=90)).date().isoformat(),
                             "dateTo": now.date().isoformat()})
    r.raise_for_status()
    matches = sorted(r.json().get("matches", []), key=lambda m: m["utcDate"])[-5:]
    form = []
    for m in matches:
        home = m["homeTeam"]["id"] == LFC
        ft = (m.get("score") or {}).get("fullTime") or {}
        us, them = (ft.get("home"), ft.get("away")) if home else (ft.get("away"), ft.get("home"))
        if us is None or them is None:
            continue
        opp = _short((m["awayTeam"] if home else m["homeTeam"]).get("shortName")
                     or (m["awayTeam"] if home else m["homeTeam"])["name"])
        form.append({
            "result": "W" if us > them else "L" if us < them else "D",
            "score": f"{us}-{them}",
            "opponent": opp,
            "venue": "H" if home else "A",
            "competition": m["competition"]["name"],
            "date": m["utcDate"],
        })

    table, matchday = [], None
    r = requests.get("https://api.football-data.org/v4/competitions/PL/standings", headers=h, timeout=20)
    r.raise_for_status()
    data = r.json()
    matchday = (data.get("season") or {}).get("currentMatchday")
    rows = ((data.get("standings") or [{}])[0]).get("table", [])
    me = next((i for i, row in enumerate(rows) if row["team"]["id"] == LFC), 0)
    # Top 4, plus Liverpool's neighbours if they're further down
    keep = set(range(min(4, len(rows)))) | set(range(max(0, me - 2), min(len(rows), me + 3)))
    for i in sorted(keep):
        row = rows[i]
        table.append({
            "pos": row["position"],
            "team": _short(row["team"].get("shortName") or row["team"]["name"]),
            "played": row["playedGames"],
            "gd": row["goalDifference"],
            "pts": row["points"],
            "me": row["team"]["id"] == LFC,
            "gap": i > 0 and (i - 1) not in keep,
        })
    return {"form": form, "table": table, "matchday": matchday}


# ---------------- F1 ----------------
def f1(cfg) -> dict:
    base = "https://api.jolpi.ca/ergast/f1/current"
    out = {}
    r = requests.get(f"{base}/driverStandings.json", timeout=20)
    r.raise_for_status()
    lists = r.json()["MRData"]["StandingsTable"]["StandingsLists"]
    if lists:
        out["round"] = lists[0].get("round")
        out["drivers"] = [{
            "pos": d["position"],
            "name": d["Driver"].get("familyName", ""),
            "team": (d.get("Constructors") or [{}])[0].get("name", ""),
            "pts": d["points"],
            "wins": d.get("wins", "0"),
        } for d in lists[0]["DriverStandings"][:5]]

    r = requests.get(f"{base}/constructorStandings.json", timeout=20)
    r.raise_for_status()
    lists = r.json()["MRData"]["StandingsTable"]["StandingsLists"]
    if lists:
        out["constructors"] = [{"pos": c["position"], "name": c["Constructor"]["name"], "pts": c["points"]}
                               for c in lists[0]["ConstructorStandings"][:3]]

    r = requests.get(f"{base}/last/results.json", timeout=20)
    r.raise_for_status()
    races = r.json()["MRData"]["RaceTable"]["Races"]
    if races:
        race = races[0]
        out["last_race"] = {
            "name": race["raceName"],
            "podium": [f"{x['Driver'].get('familyName', '')}" for x in race.get("Results", [])[:3]],
        }
    return out


# ---------------- CS2 favourite teams ----------------
def _find_team_id(headers, display: str, aliases: list[str]) -> int | None:
    names = [display] + list(aliases or [])
    wanted = {n.lower() for n in names}
    for n in names:
        r = requests.get("https://api.pandascore.co/csgo/teams", headers=headers, timeout=20,
                         params={"search[name]": n, "per_page": 50})
        if r.status_code != 200:
            continue
        for t in r.json():
            if (t.get("name") or "").lower() in wanted or (t.get("acronym") or "").lower() in wanted:
                return t["id"]
    return None


def cs2(cfg, per_team: int = 4) -> dict:
    token = get_secret("PANDASCORE_TOKEN")
    if not token:
        raise RuntimeError("PandaScore key not set")
    headers = {"Authorization": f"Bearer {token}"}
    favs = cfg.get("favourite_teams") or {}

    ids = {}
    for display, aliases in favs.items():
        if display not in _team_ids:
            tid = _find_team_id(headers, display, aliases)
            if tid:
                _team_ids[display] = tid
        if display in _team_ids:
            ids[_team_ids[display]] = display
    if not ids:
        return {"teams": []}

    r = requests.get("https://api.pandascore.co/csgo/matches/past", headers=headers, timeout=20,
                     params={"filter[opponent_id]": ",".join(str(i) for i in ids),
                             "sort": "-end_at", "per_page": 100})
    r.raise_for_status()
    results = {d: [] for d in favs}
    for m in r.json():
        if m.get("status") != "finished":
            continue
        opps = [((o or {}).get("opponent") or {}) for o in (m.get("opponents") or [])]
        score = {x.get("team_id"): x.get("score", 0) for x in (m.get("results") or [])}
        for t in opps:
            display = ids.get(t.get("id"))
            if not display or len(results[display]) >= per_team:
                continue
            other = next((o for o in opps if o.get("id") != t.get("id")), {})
            won = m.get("winner_id") == t.get("id")
            results[display].append({
                "result": "W" if won else "L",
                "score": f"{score.get(t.get('id'), 0)}-{score.get(other.get('id'), 0)}",
                "opponent": other.get("name") or "TBD",
                "event": (m.get("league") or {}).get("name", ""),
            })
    return {"teams": [{"name": d, "results": results[d]} for d in favs if d in ids.values()]}


# ---------------- Darts: PDC Order of Merit (from Wikipedia) ----------------
from html.parser import HTMLParser
import re


class _Tables(HTMLParser):
    """Collects every <table class="wikitable"> as a list of rows of cell text."""
    def __init__(self):
        super().__init__()
        self.tables, self._stack, self._row, self._cell = [], [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._stack.append("wikitable" in (a.get("class") or ""))
            if self._stack[-1] and len(self._stack) == 1:
                self.tables.append([])
        elif self._stack and self._stack[0] and len(self._stack) == 1:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th") and self._row is not None:
                self._cell = []
            elif tag in ("style", "sup"):
                self._cell_skip = True

    def handle_endtag(self, tag):
        if tag == "table" and self._stack:
            self._stack.pop()
        elif self._stack and self._stack[0] and len(self._stack) == 1:
            if tag in ("td", "th") and self._cell is not None and self._row is not None:
                self._row.append(" ".join("".join(self._cell).split()))
                self._cell = None
            elif tag == "tr" and self._row is not None:
                if self._row:
                    self.tables[-1].append(self._row)
                self._row = None
            elif tag in ("style", "sup"):
                self._cell_skip = False

    def handle_data(self, data):
        if self._cell is not None and not getattr(self, "_cell_skip", False):
            self._cell.append(data)


def darts(cfg, top: int = 16) -> dict:
    r = requests.get("https://en.wikipedia.org/w/api.php", timeout=20,
                     headers={"User-Agent": "SportsNotifier/1.0 (personal dashboard)"},
                     params={"action": "parse", "page": "PDC_Order_of_Merit", "prop": "text",
                             "format": "json", "formatversion": 2, "redirects": 1})
    r.raise_for_status()
    html = r.json()["parse"]["text"]
    parser = _Tables()
    parser.feed(html)
    for table in parser.tables:
        if not table:
            continue
        head = [h.lower() for h in table[0]]
        try:
            i_rank = next(i for i, h in enumerate(head) if h.startswith("rank") or h in ("pos", "no."))
            i_player = next(i for i, h in enumerate(head) if "player" in h)
            i_money = next(i for i, h in enumerate(head) if "earning" in h or "prize" in h or "money" in h)
        except StopIteration:
            continue
        rows = []
        for row in table[1:]:
            if len(row) <= max(i_rank, i_player, i_money):
                continue
            rank = re.sub(r"\D", "", row[i_rank])
            if not rank:
                continue
            rows.append({"pos": int(rank), "name": row[i_player].strip(), "money": row[i_money].strip()})
            if len(rows) >= top:
                break
        if rows:
            m = re.search(r"as of (\d{1,2} \w+ \d{4})", re.sub(r"<[^>]+>", " ", html))
            return {"players": rows, "as_of": m.group(1) if m else None}
    raise RuntimeError("Order of Merit table not found")


def build(cfg) -> dict:
    """All panels. Each one is independent; failures are noted, not fatal."""
    out = {}
    for name, fn, section in (("liverpool", liverpool, "liverpool"), ("f1", f1, "f1"),
                              ("cs2", cs2, "cs2"), ("darts", darts, "darts")):
        try:
            out[name] = fn(cfg.get(section, {}))
        except Exception as exc:
            log.warning("panel %s failed: %s", name, str(exc).split("?")[0][:150])
            out[name] = {"error": f"{type(exc).__name__}"}
    return out
