"""One look for every phone alert.

Every alert is built as an `Alert` and sent with `send()`, so they all follow
the same rules:
  * title  = the matchup and the one key fact (time or result)
  * body   = at most ~3 short lines: context, key info, extra
  * links  = tap buttons (ntfy actions), never URLs in the text
  * one emoji per alert (ntfy shows the first tag as an emoji before the title)
  * priority by importance: starts buzz, results are normal, summaries are quiet
"""
import re
from dataclasses import dataclass, field

# ntfy priorities
URGENT, HIGH, NORMAL, LOW = "high", "high", "default", "low"

# Long official names -> what people actually call them
TEAM_NAMES = {
    "natus vincere": "NAVI",
    "team spirit": "Spirit",
    "team falcons": "Falcons",
    "faze clan": "FaZe",
    "team vitality": "Vitality",
    "team liquid": "Liquid",
    "g2 esports": "G2",
    "mousesports": "MOUZ",
    "the mongolz": "MongolZ",
    "manchester city": "Man City",
    "manchester united": "Man United",
    "tottenham hotspur": "Spurs",
    "wolverhampton wanderers": "Wolves",
    "brighton & hove albion": "Brighton",
    "nottingham forest": "Nott'm Forest",
    "west ham united": "West Ham",
    "newcastle united": "Newcastle",
    "paris saint-germain": "PSG",
}
_SUFFIXES = (" FC", " AFC", " CF", " Esports", " Gaming", " Clan")


def short_team(name: str) -> str:
    """'Natus Vincere' -> 'NAVI', 'Team Spirit' -> 'Spirit', 'Manchester City FC' -> 'Man City'."""
    if not name:
        return "TBD"
    n = name.strip()
    for suf in _SUFFIXES:
        if n.endswith(suf) and len(n) > len(suf) + 2:
            n = n[: -len(suf)]
    if n.lower() in TEAM_NAMES:
        return TEAM_NAMES[n.lower()]
    if n.lower().startswith("team ") and len(n) > 7:
        n = n[5:]
    return n


def short_comp(name: str) -> str:
    """'ESL Pro League Season 24 2026' -> 'ESL Pro League S24'; 'Singapore Grand Prix' -> 'Singapore GP'."""
    if not name:
        return ""
    s = re.sub(r"\s+20\d\d(?=$|\s*[·:-])", "", name.strip())
    s = re.sub(r"\bSeason\s+(\d+)", r"S\1", s, flags=re.I)
    s = s.replace("Grand Prix", "GP").replace("UEFA ", "")
    return " ".join(s.split())


ROUNDS = [
    (r"grand final", "Grand final"),
    (r"quarter[- ]?finals?", "QF"),
    (r"semi[- ]?finals?", "SF"),
    (r"^finals?$", "Final"),
    (r"round of (\d+)", r"Last \1"),
    (r"^round (\d+)$", r"R\1"),
]


def short_round(name: str) -> str:
    """'Quarterfinals' -> 'QF', 'Round 1' -> 'R1'; anything else is kept."""
    n = (name or "").strip()
    for pat, rep in ROUNDS:
        if re.search(pat, n, flags=re.I):
            return re.sub(pat, rep, n, flags=re.I) if "\\" in rep else rep
    return n


def surname(name: str) -> str:
    parts = (name or "").split()
    if len(parts) >= 3 and parts[-2].lower() in ("van", "de", "der", "von"):
        return " ".join(parts[-2:])        # Michael van Gerwen -> van Gerwen
    return parts[-1] if parts else "?"


def ordinal(n) -> str:
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def dash(a, b) -> str:
    return f"{a}–{b}"


def join(*parts, sep=" · ") -> str:
    return sep.join(str(p) for p in parts if p)


@dataclass
class Alert:
    key: str                     # state key: each alert is sent once
    title: str
    lines: list = field(default_factory=list)
    emoji: str = ""              # one ntfy tag, shown as an emoji before the title
    click: str = ""              # where tapping the notification goes
    priority: str = NORMAL
    actions: list = field(default_factory=list)   # [(label, url)], max 3

    @property
    def body(self) -> str:
        return "\n".join(l for l in self.lines if l) or " "


def actions_header(actions) -> str:
    """ntfy 'Actions' header: view buttons that open a link."""
    out = []
    for label, url in [a for a in actions if a and a[1]][:3]:
        label = label.replace(",", " ").replace(";", " ")
        url = f'"{url}"' if ("," in url or ";" in url) else url
        out.append(f"view, {label}, {url}")
    return "; ".join(out)
