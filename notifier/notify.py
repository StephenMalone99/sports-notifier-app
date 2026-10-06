"""Phone alerts via ntfy. Designed to run every hour (GitHub Actions or your PC).

Sends:
  * a morning digest (once a day, from `daily_digest_hour`) of today's events
    and tournaments starting tomorrow
  * a reminder before each Liverpool kick-off

Already-sent alerts are remembered in state/sent.json so nothing repeats.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .collect import ROOT, collect, load_config
from .keystore import get_secret
from .models import Event

STATE = ROOT / "state" / "sent.json"
ICON = {"cs2": "video_game", "darts": "dart", "liverpool": "soccer"}
log = logging.getLogger("notifier")


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_state(state: dict):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    state = {k: v for k, v in state.items() if v >= cutoff}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def push(cfg, title: str, body: str, tags: str = "", click: str = "", priority: str = "default"):
    topic = get_secret("NTFY_TOPIC")
    if not topic:
        log.warning("NTFY_TOPIC not set — would have sent: %s", title)
        return False
    server = cfg.get("notifications", {}).get("ntfy_server", "https://ntfy.sh").rstrip("/")
    headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore"), "Priority": priority}
    if tags:
        headers["Tags"] = tags
    if click:
        headers["Click"] = click
    r = requests.post(f"{server}/{topic}", data=body.encode("utf-8"), headers=headers, timeout=20)
    r.raise_for_status()
    return True


def _day_of(e: Event, day, tz) -> str:
    first = e.start.astimezone(tz).date()
    last = (e.end or e.start).astimezone(tz).date()
    total = (last - first).days + 1
    return f"day {(day - first).days + 1} of {total}" if total > 1 else "one day"


def build_digest(events: list[Event], day, tz, max_matches: int = 12) -> str | None:
    """Plain-text morning summary for `day` (a local date), or None if nothing is on."""

    def on(e, d):
        s = e.start.astimezone(tz).date()
        f = (e.end or e.start).astimezone(tz).date()
        return s <= d <= f

    t = lambda e: e.start.astimezone(tz).strftime("%H:%M")
    parts = []

    # Liverpool
    lfc = [e for e in events if e.sport == "liverpool" and on(e, day)]
    if lfc:
        parts.append("LIVERPOOL\n" + "\n".join(
            f"{t(e)}  {e.title}\n       {e.competition} · {e.detail}" for e in lfc))

    # CS2: each tracked event with today's matches underneath
    tournaments = [e for e in events if e.sport == "cs2" and e.all_day and on(e, day)]
    matches = [e for e in events if e.sport == "cs2" and "match" in e.tags and on(e, day)]
    for tr in tournaments:
        serie = next((x for x in tr.tags if x.startswith("serie-")), None)
        mine = [m for m in matches if serie in m.tags]
        lines = [f"CS2 · {tr.title} ({_day_of(tr, day, tz)})"]
        if mine:
            for m in mine[:max_matches]:
                lines.append(f"{t(m)}  {m.title}" + (f"  ({m.detail})" if m.detail else ""))
            if len(mine) > max_matches:
                lines.append(f"…and {len(mine) - max_matches} more")
        else:
            lines.append("No matches scheduled today (rest day or not announced yet)")
        parts.append("\n".join(lines))

    # Darts
    for e in [e for e in events if e.sport == "darts" and on(e, day)]:
        if e.all_day:
            parts.append(f"DARTS · {e.title} ({_day_of(e, day, tz)})\n"
                         + (f"{e.detail}\n" if e.detail else "") + "Order of play: pdc.tv")
        else:
            parts.append(f"DARTS · {e.title}\n{t(e)} start" + (f" · {e.detail}" if e.detail else ""))

    if not parts:
        return None

    # Heads-up for tomorrow (event starts / Liverpool / darts nights; not every CS2 match)
    tomorrow = day + timedelta(days=1)
    soon = [e for e in events if e.start.astimezone(tz).date() == tomorrow and "match" not in e.tags]
    if soon:
        parts.append("TOMORROW\n" + "\n".join(
            (f"{e.title} starts" if e.all_day else f"{t(e)}  {e.title}") for e in soon))

    body = "\n\n".join(parts)
    return body if len(body.encode()) < 3900 else body[:3800] + "\n…(see dashboard)"


def run(now: datetime | None = None, events: list[Event] | None = None):
    cfg = load_config()
    tz = ZoneInfo(cfg.get("timezone", "Europe/Dublin"))
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    if events is None:
        payload = collect(cfg)
        for name, s in payload["status"].items():
            print(f"{name:10} {'OK  ' + str(s['count']) + ' events' if s['ok'] else 'FAILED  ' + s['error']}")
        events = [Event.from_dict(d) for d in payload["events"]]
        print("Next up:")
        for e in events[:12]:
            print(f"  {e.start.astimezone(tz):%a %d %b %H:%M}  [{e.sport}] {e.title}")
    state = _load_state()
    sent = []

    # 1) Liverpool kick-off reminders
    lead = timedelta(minutes=cfg.get("liverpool", {}).get("remind_minutes_before", 60))
    for e in events:
        if e.sport != "liverpool":
            continue
        key = f"ko-{e.id}"
        if key not in state and now < e.start <= now + lead + timedelta(minutes=30):
            mins = int((e.start - now).total_seconds() // 60)
            if push(cfg, f"Liverpool kick off in {mins} min",
                    f"{e.title}\n{e.competition} · {e.start.astimezone(tz):%H:%M}\n{e.detail}",
                    tags="soccer,red_circle", click=e.url, priority="high"):
                state[key] = now.isoformat()
                sent.append(key)

    # 2) Morning digest
    digest_key = f"digest-{local.date().isoformat()}"
    if local.hour >= cfg.get("notifications", {}).get("daily_digest_hour", 9) and digest_key not in state:
        body = build_digest(events, local.date(), tz)
        if body:
            tags = ",".join(sorted({ICON[e.sport] for e in events
                                    if e.sport.upper() in body.upper()} or {"calendar"}))
            if push(cfg, f"Sports today - {local:%a %d %b}", body, tags=tags):
                sent.append(digest_key)
        state[digest_key] = now.isoformat()  # mark done even if nothing was on

    _save_state(state)
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Sent:", run() or "nothing due")
