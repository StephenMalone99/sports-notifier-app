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


def _line(e: Event, tz) -> str:
    if e.all_day:
        end = f" to {e.end.astimezone(tz):%a %d %b}" if e.end else ""
        return f"{e.title} ({e.start.astimezone(tz):%a %d %b}{end})"
    return f"{e.start.astimezone(tz):%H:%M} {e.title} ({e.competition})"


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
        for e in events[:8]:
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
        today, tomorrow = local.date(), local.date() + timedelta(days=1)

        def on(e, day):
            s = e.start.astimezone(tz).date()
            f = (e.end or e.start).astimezone(tz).date()
            return s <= day <= f

        today_events = [e for e in events if on(e, today)]
        starting_tomorrow = [e for e in events if e.start.astimezone(tz).date() == tomorrow]
        if today_events or starting_tomorrow:
            parts = []
            if today_events:
                parts.append("TODAY\n" + "\n".join(f"- {_line(e, tz)}" for e in today_events))
            if starting_tomorrow:
                parts.append("STARTS TOMORROW\n" + "\n".join(f"- {_line(e, tz)}" for e in starting_tomorrow))
            tags = ",".join(sorted({ICON[e.sport] for e in today_events + starting_tomorrow}))
            if push(cfg, f"Sports today - {local:%a %d %b}", "\n\n".join(parts), tags=tags):
                sent.append(digest_key)
        state[digest_key] = now.isoformat()  # mark done even if nothing was on

    _save_state(state)
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Sent:", run() or "nothing due")
