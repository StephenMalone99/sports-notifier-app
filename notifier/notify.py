"""Phone alerts via ntfy. Designed to run every hour (GitHub Actions or your PC).

Sends:
  * a morning digest (once a day, from `daily_digest_hour`) of today's events
    and tournaments starting tomorrow
  * a reminder before each Liverpool kick-off

Already-sent alerts are remembered in state/sent.json so nothing repeats.
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from .collect import ROOT, collect, load_config
from .keystore import get_secret
from .models import Event

STATE = ROOT / "state" / "sent.json"
ICON = {"cs2": "video_game", "darts": "dart", "liverpool": "soccer", "f1": "checkered_flag"}
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


def _tag(e: Event, prefix: str) -> str:
    return next((x[len(prefix):] for x in e.tags if x.startswith(prefix)), "")


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
    star = lambda e: "★ " if "fav" in e.tags else ""
    parts = []

    # Your CS2 teams (any event)
    favs = [e for e in events if "fav" in e.tags and "match" in e.tags and on(e, day)]
    if favs:
        parts.append("YOUR TEAMS\n" + "\n".join(
            f"{t(e)}  {e.title}\n       {e.competition}" + (f" · {e.detail}" if e.detail else "")
            + (f"\n       Watch: {_tag(e, 'watch:')}" if _tag(e, 'watch:') else "")
            for e in favs))

    # Liverpool
    lfc = [e for e in events if e.sport == "liverpool" and on(e, day)]
    if lfc:
        parts.append("LIVERPOOL\n" + "\n".join(
            f"{t(e)}  {e.title}\n       {e.competition} · {e.detail}"
            + (f"\n       TV: {_tag(e, 'tv:')}" if _tag(e, 'tv:') else "") for e in lfc))

    # CS2: each tracked event with today's matches underneath
    tournaments = [e for e in events if e.sport == "cs2" and e.all_day and on(e, day)]
    matches = [e for e in events if e.sport == "cs2" and "match" in e.tags and on(e, day)]
    for tr in tournaments:
        serie = next((x for x in tr.tags if x.startswith("serie-")), None)
        mine = [m for m in matches if serie in m.tags]
        lines = [f"CS2 · {tr.title} ({_day_of(tr, day, tz)})"]
        if mine:
            for m in mine[:max_matches]:
                lines.append(f"{t(m)}  {star(m)}{m.title}" + (f"  ({m.detail})" if m.detail else ""))
            if len(mine) > max_matches:
                lines.append(f"…and {len(mine) - max_matches} more")
            streams = [_tag(m, "watch:") for m in mine if _tag(m, "watch:")]
            if streams:
                lines.append("Watch: " + max(set(streams), key=streams.count))
        else:
            lines.append("No matches scheduled today (rest day or not announced yet)")
        parts.append("\n".join(lines))

    # F1: today's sessions, grouped by Grand Prix
    f1 = [e for e in events if e.sport == "f1" and on(e, day)]
    for gp in dict.fromkeys(e.title.split(" - ")[0] for e in f1):
        mine = [e for e in f1 if e.title.startswith(gp)]
        lines = [f"F1 · {gp}" + (f" ({mine[0].detail})" if mine[0].detail else "")]
        lines += [f"{t(e)}  {_tag(e, 'session:')}" for e in mine]
        if _tag(mine[0], "tv:"):
            lines.append(f"TV: {_tag(mine[0], 'tv:')}")
        parts.append("\n".join(lines))

    # Darts: today's event(s), with the match-ups underneath when available
    d_matches = [e for e in events if e.sport == "darts" and "match" in e.tags and on(e, day)]
    for e in [e for e in events if e.sport == "darts" and "match" not in e.tags and on(e, day)]:
        if e.all_day:
            lines = [f"DARTS · {e.title} ({_day_of(e, day, tz)})"] + ([e.detail] if e.detail else [])
        else:
            lines = [f"DARTS · {e.title}", f"{t(e)} start" + (f" · {e.detail}" if e.detail else "")]
        if d_matches:
            for m in d_matches[:max_matches]:
                lines.append(f"{t(m)}  {m.title}" + (f"  ({m.detail})" if m.detail else ""))
            if len(d_matches) > max_matches:
                lines.append(f"…and {len(d_matches) - max_matches} more")
            d_matches = []                  # list them once, under the first event
        else:
            lines.append("Order of play: pdc.tv")
        parts.append("\n".join(lines))

    if not parts:
        return None

    # Heads-up for tomorrow (event starts / Liverpool / darts nights; not every CS2 match)
    tomorrow = day + timedelta(days=1)
    soon = [e for e in events if e.start.astimezone(tz).date() == tomorrow
            and ("match" not in e.tags or "fav" in e.tags)]
    if soon:
        parts.append("TOMORROW\n" + "\n".join(
            (f"{e.title} starts" if e.all_day else f"{t(e)}  {star(e)}{e.title}") for e in soon))

    body = "\n\n".join(parts)
    return body if len(body.encode()) < 3900 else body[:3800] + "\n…(see dashboard)"


def run(now: datetime | None = None, events: list[Event] | None = None):
    cfg = load_config()
    tz = ZoneInfo(cfg.get("timezone", "Europe/Dublin"))
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    status = {}
    if events is None:
        payload = collect(cfg)
        status = payload["status"]
        for name, s in payload["status"].items():
            print(f"{name:10} {'OK  ' + str(s['count']) + ' events' if s['ok'] else 'FAILED  ' + s['error']}")
        events = [Event.from_dict(d) for d in payload["events"]]
        print("Next up:")
        for e in events[:12]:
            print(f"  {e.start.astimezone(tz):%a %d %b %H:%M}  [{e.sport}] {'★ ' if 'fav' in e.tags else ''}{e.title}")
        favs = [e for e in events if "fav" in e.tags and "match" in e.tags]
        print(f"Favourite-team matches: {len(favs)}")
        for e in favs[:8]:
            print(f"  {e.start.astimezone(tz):%a %d %b %H:%M}  {e.title}  ({e.competition})")
    state = _load_state()
    sent = []

    # 1b) Favourite CS2 team reminders
    lead = timedelta(minutes=cfg.get("cs2", {}).get("remind_minutes_before", 60))
    for e in events:
        if not ("fav" in e.tags and "match" in e.tags):
            continue
        key = f"fav-{e.id}"
        if key not in state and now < e.start <= now + lead + timedelta(minutes=30):
            mins = int((e.start - now).total_seconds() // 60)
            who = " & ".join(x[5:] for x in e.tags if x.startswith("team:")) or "Your team"
            if push(cfg, f"{who} play in {mins} min",
                    f"{e.title}\n{e.competition}" + (f" · {e.detail}" if e.detail else "")
                    + f"\n{e.start.astimezone(tz):%H:%M}"
                    + (f" · Watch: {_tag(e, 'watch:')}" if _tag(e, 'watch:') else " · tap to watch"),
                    tags="video_game,star", click=e.url, priority="high"):
                state[key] = now.isoformat()
                sent.append(key)

    # 1c) F1 session reminders
    fc = cfg.get("f1", {})
    lead = timedelta(minutes=fc.get("remind_minutes_before", 60))
    remind = set(fc.get("remind", ["Qualifying", "Sprint", "Race"]))
    for e in events:
        if e.sport != "f1" or _tag(e, "session:") not in remind:
            continue
        key = f"f1-{e.id}"
        if key not in state and now < e.start <= now + lead + timedelta(minutes=30):
            mins = int((e.start - now).total_seconds() // 60)
            if push(cfg, f"F1 {_tag(e, 'session:')} in {mins} min",
                    f"{e.title.split(' - ')[0]}\n{e.detail}\n{e.start.astimezone(tz):%H:%M}"
                    + (f" · TV: {_tag(e, 'tv:')}" if _tag(e, "tv:") else ""),
                    tags="checkered_flag", click=e.url, priority="high"):
                state[key] = now.isoformat()
                sent.append(key)

    # 1d) Results (optional)
    rc = cfg.get("results", {})
    if rc.get("enabled", True):
        from . import results
        from .sources.cs2 import _fav_aliases
        jobs = []
        if rc.get("liverpool", True):
            jobs.append(("liverpool", lambda: results.liverpool(cfg, now)))
        if rc.get("cs2_favourites", True):
            jobs.append(("cs2", lambda: results.cs2(cfg, now, _fav_aliases(cfg.get("cs2", {})))))
        if rc.get("f1", True):
            jobs.append(("f1", lambda: results.f1(cfg, now)))
        if rc.get("darts", True):
            jobs.append(("darts", lambda: results.darts(cfg, now, events)))
        for name, job in jobs:
            try:
                for key, title, body, tags, click in job():
                    if key not in state and push(cfg, title, body, tags=tags, click=click):
                        state[key] = now.isoformat()
                        sent.append(key)
            except Exception as exc:
                log.warning("%s results failed: %s", name, str(exc).split("?")[0][:150])

    # 1e) Health: tell me if a source keeps failing, or the darts calendar runs out
    if status:
        sent += _health(cfg, status, state, now, local)

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

    # 3) Liverpool kick-off reminder (last, because it may wait for line-ups)
    sent += _liverpool_reminders(cfg, events, state, now, tz)
    _save_state(state)
    return sent


def _liverpool_reminders(cfg, events, state, now, tz, sleep=None, clock=None) -> list:
    """Ping before kick-off. If line-ups are on, wait (polling every 5 min) until
    the starting XIs are out, or until 40 min before kick-off, whichever is first."""
    lc = cfg.get("liverpool", {})
    lead = timedelta(minutes=lc.get("remind_minutes_before", 60))
    clock = clock or (lambda: datetime.now(timezone.utc))
    sleep = sleep or time.sleep
    sent = []
    for e in events:
        key = f"ko-{e.id}"
        if e.sport != "liverpool" or key in state:
            continue
        # window is wide enough that one hourly run always catches it
        if not (now < e.start <= now + lead + timedelta(minutes=50)):
            continue
        lineup = None
        if lc.get("lineups", True):
            from .lineups import fetch_lineup
            while True:
                lineup = fetch_lineup(e, lc.get("sportsapipro_team_id", 44))
                left = e.start - clock()
                if lineup or left <= timedelta(minutes=40):
                    break
                print(f"Waiting for line-ups ({int(left.total_seconds() // 60)} min to kick-off)…")
                sleep(300)
        mins = max(0, int((e.start - clock()).total_seconds() // 60))
        tv = _tag(e, "tv:")
        body = (f"{e.title}\n{e.competition} · {e.start.astimezone(tz):%H:%M}\n{e.detail}"
                + (f"\nTV: {tv}" if tv else "")
                + (f"\n\n{lineup}" if lineup else ("\n\nLine-ups not out yet" if lc.get("lineups", True) else "")))
        title = f"Liverpool kick off in {mins} min" + (" - line-ups in" if lineup else "")
        if push(cfg, title, body, tags="soccer,red_circle", click=e.url, priority="high"):
            state[key] = clock().isoformat()
            sent.append(key)
    return sent


def _health(cfg, status, state, now, local) -> list:
    """Alert when a source has been failing for over 90 minutes (once a day),
    and once a month when the darts calendar is about to run out."""
    sent = []
    for name, s in status.items():
        flag = f"failing-{name}"
        if s.get("ok"):
            state.pop(flag, None)
            continue
        first = state.setdefault(flag, now.isoformat())
        key = f"fail-{name}-{local.date().isoformat()}"
        if now - datetime.fromisoformat(first) >= timedelta(minutes=90) and key not in state:
            if push(cfg, f"Notifier problem: {name} not updating",
                    f"{s.get('error', 'unknown error')}\n\nCheck the latest run under GitHub → Actions.",
                    tags="warning", priority="high"):
                state[key] = now.isoformat()
                sent.append(key)
    try:
        from .sources import darts
        last = max((e.end or e.start) for e in darts.fetch({}))
        key = f"darts-calendar-{local:%Y-%m}"
        if last - now < timedelta(days=60) and key not in state:
            if push(cfg, "Update the darts calendar",
                    f"data/darts.yaml runs out on {last:%d %b %Y}. "
                    "Add next season's dates from pdc.tv/calendar.", tags="dart,memo"):
                state[key] = now.isoformat()
                sent.append(key)
    except Exception as exc:
        log.warning("darts calendar check failed: %s", exc)
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        print("Sent:", run() or "nothing due")
    except Exception as exc:
        # Last resort: the whole run crashed - say so on the phone, then fail the job
        try:
            push(load_config(), "Notifier crashed",
                 f"{type(exc).__name__}: {str(exc)[:300]}\n\nCheck GitHub → Actions.",
                 tags="rotating_light", priority="high")
        finally:
            raise
