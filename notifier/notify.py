"""Phone alerts via ntfy. Designed to run every 10 minutes (GitHub Actions or your PC).
Every run is a quick check - nothing waits inside a run, so runs never queue.

Sends:
  * a morning digest (once a day, at `daily_digest_time`) of today's events
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

from . import enrich
from .collect import ROOT, collect, load_config
from .keystore import get_secret
from .format import (HIGH, LOW, NORMAL, Alert, dash, join, ordinal, short_comp,
                     short_round, short_team, surname)
from .models import Event

STATE = ROOT / "state" / "sent.json"
ICON = {"cs2": "video_game", "darts": "dart", "liverpool": "soccer", "f1": "checkered_flag"}
log = logging.getLogger("notifier")
SLACK = timedelta(minutes=5)   # reminders go out lead..lead+5 min before (runs are every 10 min)


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _save_state(state: dict):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    state = {k: v for k, v in state.items() if v.split("|")[-1] >= cutoff}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "max": 5, "urgent": 5}


def push(cfg, title: str, body: str, tags: str = "", click: str = "", priority: str = "default",
         actions=None):
    """Publish one notification. Uses ntfy's JSON API so titles keep every character
    (en dashes, accents) and tap buttons are sent cleanly."""
    topic = get_secret("NTFY_TOPIC")
    if not topic:
        log.warning("NTFY_TOPIC not set — would have sent: %s", title)
        return False
    server = cfg.get("notifications", {}).get("ntfy_server", "https://ntfy.sh").rstrip("/")
    msg = {"topic": topic, "title": title, "message": body or " ",
           "priority": PRIORITY.get(priority, 3)}
    if tags:
        msg["tags"] = [t for t in tags.split(",") if t]
    if click:
        msg["click"] = click
    if actions:
        msg["actions"] = [{"action": "view", "label": label, "url": url, "clear": False}
                          for label, url in actions if url][:3]
    for attempt in range(3):   # ntfy.sh occasionally drops a connection - retry before giving up
        try:
            r = requests.post(server, json=msg, timeout=20)
            r.raise_for_status()
            return True
        except requests.RequestException as exc:
            log.warning("ntfy send failed (try %d/3) for %r: %s", attempt + 1, title,
                        type(exc).__name__)
            if attempt < 2:
                time.sleep(10)
    return False   # not marked as sent, so the next run tries again


def send(cfg, alert: Alert, state: dict, sent: list, now) -> bool:
    """Send an Alert once: skipped if its key is already in state."""
    if alert.key in state:
        return False
    ok = push(cfg, alert.title, alert.body, tags=alert.emoji, click=alert.click,
              priority=alert.priority, actions=alert.actions)
    if ok:
        state[alert.key] = now.isoformat()
        sent.append(alert.key)
    return ok


def _digest_time(cfg) -> tuple[int, int]:
    nc = cfg.get("notifications", {})
    t = str(nc.get("daily_digest_time") or f"{nc.get('daily_digest_hour', 9)}:00")
    h, _, m = t.partition(":")
    return int(h), int(m or 0)


def _tag(e: Event, prefix: str) -> str:
    return next((x[len(prefix):] for x in e.tags if x.startswith(prefix)), "")


def _day_of(e: Event, day, tz) -> str:
    first = e.start.astimezone(tz).date()
    last = (e.end or e.start).astimezone(tz).date()
    total = (last - first).days + 1
    return f"day {(day - first).days + 1} of {total}" if total > 1 else "one day"


def build_digest(events: list[Event], day, tz, players=(), max_lines: int = 18) -> str | None:
    """Morning summary for `day`: one line per item, only sections with something on."""

    def on(e, d):
        s = e.start.astimezone(tz).date()
        f = (e.end or e.start).astimezone(tz).date()
        return s <= d <= f

    t = lambda e: e.start.astimezone(tz).strftime("%H:%M")
    vs = lambda title: title.replace(" vs ", " v ")
    sections = []

    # CS2: your teams' matches, then which tracked events are running
    favs = sorted([e for e in events if "fav" in e.tags and "match" in e.tags and on(e, day)
                   and e.start.astimezone(tz).date() == day], key=lambda e: e.start)
    events_on = [e for e in events if e.sport == "cs2" and e.all_day and on(e, day)]
    if favs or events_on:
        lines = ["CS2"]
        for e in favs:
            bo = _tag(e, "bo:")
            lines.append(f"{t(e)}  {vs(e.title)}" + (f" · Bo{bo}" if bo else ""))
        if events_on:
            lines.append("On: " + ", ".join(f"{short_comp(e.title)} ({_day_of(e, day, tz)})"
                                            for e in events_on[:3]))
        sections.append(lines)

    # Liverpool
    lfc = [e for e in events if e.sport == "liverpool" and on(e, day)]
    if lfc:
        sections.append(["Liverpool"] + [
            f"{t(e)}  {vs(e.title)} · " + join(short_comp(e.competition), _tag(e, "tv:"))
            for e in lfc])

    # F1: today's sessions under the Grand Prix name
    f1 = [e for e in events if e.sport == "f1" and on(e, day)]
    for gp in dict.fromkeys(e.title.split(" - ")[0] for e in f1):
        mine = [e for e in f1 if e.title.startswith(gp)]
        sections.append([f"F1 · {short_comp(gp)}"] + [f"{t(e)}  {_tag(e, 'session:')}" for e in mine])

    # Darts: today's event, plus your players' matches (and finals/semis)
    d_events = [e for e in events if e.sport == "darts" and "match" not in e.tags and on(e, day)]
    if d_events:
        surnames = [p.split()[-1].lower() for p in players]
        picks = [m for m in events if m.sport == "darts" and "match" in m.tags and on(m, day)
                 and (any(s in m.title.lower() for s in surnames)
                      or any(w in _tag(m, "round:").lower() for w in ("final", "semi")))]
        for e in d_events:
            head = (f"Darts · {short_comp(e.title)} ({_day_of(e, day, tz)})" if e.all_day
                    else f"Darts · {short_comp(e.title.replace(' - ', ' · '))} · {t(e)}")
            lines = [head]
            for m in sorted(picks, key=lambda m: m.start)[:6]:
                rnd = short_round(_tag(m, "round:"))
                pair = " v ".join(surname(x) for x in m.title.split(" vs "))
                lines.append(f"{t(m)}  {pair}" + (f" · {rnd}" if rnd else ""))
            picks = []                         # list them once, under the first event
            sections.append(lines)

    if not sections:
        return None

    # Tomorrow, on one line: your matches, Liverpool, F1 sessions, events starting
    tomorrow = day + timedelta(days=1)
    soon = []
    for e in sorted(events, key=lambda e: e.start):
        if e.start.astimezone(tz).date() != tomorrow:
            continue
        if e.all_day:
            soon.append(f"{short_comp(e.title)} starts")
        elif e.sport == "f1":
            soon.append(f"{t(e)} F1 {_tag(e, 'session:')}")
        elif e.sport == "liverpool" or ("fav" in e.tags and "match" in e.tags):
            soon.append(f"{t(e)} {vs(e.title)}")
        elif e.sport == "darts" and "match" not in e.tags:
            soon.append(f"{t(e)} {short_comp(e.title.split(' - ')[0])}")

    lines = []
    for sec in sections:
        lines += sec + [""]
    if soon:
        lines.append("Tomorrow: " + " · ".join(soon[:5]))
    lines = [l for l in lines][:max_lines]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


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
    sent += _timing(cfg, state, now, local)

    # 1a) Time changes and postponements (before reminders, so a moved match
    #     gets a fresh reminder for its new time)
    sent += _changes(cfg, events, state, now, tz)

    # 1b) Favourite CS2 team reminders
    lead = timedelta(minutes=cfg.get("cs2", {}).get("remind_minutes_before", 60))
    for e in events:
        if not ("fav" in e.tags and "match" in e.tags):
            continue
        if f"fav-{e.id}" not in state and now < e.start <= now + lead + SLACK:
            form = [f"{name} {f}" for tid, name in _tids(e) if (f := enrich.cs2_form(tid))]
            send(cfg, Alert(
                key=f"fav-{e.id}",
                title=f"{e.title} · {e.start.astimezone(tz):%H:%M}",
                lines=[_cs2_context(e), "Form: " + " · ".join(form) if form else ""],
                emoji="video_game", click=e.url, priority=HIGH, actions=_cs2_actions(e),
            ), state, sent, now)

    # 1c) F1 session reminders
    fc = cfg.get("f1", {})
    lead = timedelta(minutes=fc.get("remind_minutes_before", 60))
    remind = set(fc.get("remind", ["Qualifying", "Sprint", "Race"]))
    for e in events:
        if e.sport != "f1" or _tag(e, "session:") not in remind:
            continue
        if f"f1-{e.id}" not in state and now < e.start <= now + lead + SLACK:
            rnd = e.competition.replace("F1 ", "").split(" · ")[0]          # "Round 19"
            send(cfg, Alert(
                key=f"f1-{e.id}",
                title=f"{short_comp(e.title.split(' - ')[0])} · {_tag(e, 'session:')} · "
                      f"{e.start.astimezone(tz):%H:%M}",
                lines=[join(e.detail, rnd), f"TV: {_tag(e, 'tv:')}" if _tag(e, "tv:") else ""],
                emoji="checkered_flag", click=F1_TIMING, priority=HIGH,
                actions=[("Live timing", F1_TIMING)],
            ), state, sent, now)

    # 1d) Results (optional)
    rc = cfg.get("results", {})
    if rc.get("enabled", True):
        from . import results
        from .sources.cs2 import _fav_aliases
        jobs = []
        if rc.get("liverpool", True):
            jobs.append(("liverpool", lambda: results.liverpool(cfg, now, state)))
        if rc.get("cs2_favourites", True):
            watch = _cs2_watch(events, state, now)
            jobs.append(("cs2", lambda: results.cs2(cfg, now, _fav_aliases(cfg.get("cs2", {})),
                                                    watch_ids=watch, events=events, tz=tz)))
        if rc.get("f1", True):
            jobs.append(("f1", lambda: results.f1(cfg, now, tz, events=events)))
        if rc.get("darts", True):
            jobs.append(("darts", lambda: results.darts(cfg, now, events)))
        for name, job in jobs:
            try:
                for alert in job():
                    send(cfg, alert, state, sent, now)
            except Exception as exc:
                log.warning("%s results failed: %s", name, str(exc).split("?")[0][:150])

    # 1e) Health: tell me if a source keeps failing, or the darts calendar runs out
    if status:
        sent += _health(cfg, status, state, now, local)

    # 2) Morning digest
    digest_key = f"digest-{local.date().isoformat()}"
    if (local.hour, local.minute) >= _digest_time(cfg) and digest_key not in state:
        body = build_digest(events, local.date(), tz,
                            players=cfg.get("darts", {}).get("results_players", []))
        if body:
            if push(cfg, f"Today · {local:%a %d %b}", body, tags="calendar", priority=LOW):
                sent.append(digest_key)
        state[digest_key] = now.isoformat()  # mark done even if nothing was on

    _save_state(state)

    # 2b) Favourite CS2 matches around start time: running late / live now
    try:
        sent += _cs2_live_watch(cfg, events, state, now, tz)
    except Exception as exc:
        log.warning("CS2 live watch failed: %s", str(exc).split("?")[0][:150])
    _save_state(state)

    # 3) Liverpool kick-off reminder (sent once the line-ups are out)
    sent += _liverpool_reminders(cfg, events, state, now, tz)
    _save_state(state)
    return sent


def _liverpool_reminders(cfg, events, state, now, tz) -> list:
    """Kick-off alert. With line-ups on, each run (every 10 min) checks for the
    starting XIs from ~75 min before kick-off and sends as soon as they're out -
    or at 40 min before kick-off without them."""
    lc = cfg.get("liverpool", {})
    lead = timedelta(minutes=lc.get("remind_minutes_before", 60))
    want_lineups = lc.get("lineups", True)
    sent = []
    for e in events:
        key = f"ko-{e.id}"
        if e.sport != "liverpool" or key in state or "postponed" in e.tags:
            continue
        left = e.start - now
        if not (timedelta(0) < left <= lead + timedelta(minutes=15)):
            continue
        teams = None
        if want_lineups:
            from .lineups import fetch_lineups
            try:
                teams = fetch_lineups(e, lc.get("sportsapipro_team_id", 44))
            except Exception as exc:
                log.info("line-ups check failed: %s", str(exc).split("?")[0][:120])
            if not teams and left > timedelta(minutes=40):
                print(f"Line-ups not out yet ({int(left.total_seconds() // 60)} min to kick-off) - will check next run")
                continue

        # Context: competition · matchday · league positions ("2nd v 1st")
        code, md = _tag(e, "fdcomp:"), _tag(e, "md:")
        table = enrich.fd_table(code) if code in ("PL", "CL") else {}
        pos = [table.get(int(x))[0] if x.isdigit() and table.get(int(x)) else None
               for x in (_tag(e, "hid:"), _tag(e, "aid:"))]
        positions = f"{ordinal(pos[0])} v {ordinal(pos[1])}" if all(pos) else ""
        lines = [join(short_comp(e.competition), f"MD{md}" if md else "", positions)]
        if teams:
            lines += [f"{short_team(t)}" + (f" ({f})" if f else "") + ": " + ", ".join(xi)
                      for t, f, xi in teams[:2]]
        elif want_lineups:
            lines.append("Line-ups not out yet")
        if _tag(e, "tv:"):
            lines.append(f"TV: {_tag(e, 'tv:')}")
        send(cfg, Alert(
            key=key, title=f"{e.title} · {e.start.astimezone(tz):%H:%M}", lines=lines,
            emoji="soccer", click=BBC_LFC, priority=HIGH, actions=[("Match centre", BBC_LFC)],
        ), state, sent, now)
    return sent


def _cs2_live_watch(cfg, events, state, now, tz) -> list:
    """Favourite CS2 matches around start time, checked once per run (no waiting):
      * 'Live now' when PandaScore shows it running
      * 'Running late' once it's late_after_minutes past its time and not started,
        then 'Still not started' every 30 min (up to 3 more), so repeated
        delays keep you posted. New start times come from _changes ('Delayed')."""
    cc = cfg.get("cs2", {})
    if not cc.get("live_alerts", True):
        return []
    late_after = timedelta(minutes=cc.get("late_after_minutes", 10))
    sent = []
    for e in events:
        if not ("fav" in e.tags and "match" in e.tags):
            continue
        if "live" in e.tags:
            key = f"live-{e.id}"
            if key not in state and e.start >= now - timedelta(minutes=45):
                send(cfg, Alert(
                    key=key, title=f"LIVE: {e.title}",
                    lines=[_cs2_context(e), f"Started {e.start.astimezone(tz):%H:%M}"],
                    emoji="red_circle", click=e.url, priority=HIGH, actions=_cs2_actions(e),
                ), state, sent, now)
            continue
        overdue = now - e.start
        if overdue < late_after or overdue > timedelta(hours=3):
            continue
        key = f"late-{e.id}"
        count = int(state.get(f"latecount-{e.id}", "0|").split("|")[0])
        last = state.get(key)
        if count >= 4 or (last and now - datetime.fromisoformat(last) < timedelta(minutes=30)):
            continue
        mins = int(overdue.total_seconds() // 60)
        title = f"Running late: {e.title}" if count == 0 else f"Still not started: {e.title}"
        if push(cfg, title,
                f"Due {e.start.astimezone(tz):%H:%M} · {mins} min late\n"
                f"You'll get a ping when it goes live",
                tags="hourglass", click=e.url, actions=_cs2_actions(e)):
            state[key] = now.isoformat()
            # "count|timestamp" keeps the entry fresh for the 45-day state cleanup
            state[f"latecount-{e.id}"] = f"{count + 1}|{now.isoformat()}"
            sent.append(key)
    return sent


F1_TIMING = "https://www.formula1.com/en/timing/f1-live"
BBC_LFC = "https://www.bbc.co.uk/sport/football/teams/liverpool/scores-fixtures"


def _tids(e: Event) -> list:
    """[(pandascore team id, short name)] from a CS2 match event."""
    out = []
    for t in e.tags:
        if t.startswith("tid:"):
            _, tid, name = t.split(":", 2)
            out.append((tid, name))
    return out


def _cs2_context(e: Event) -> str:
    """'ESL Pro League S24 · Upper bracket final · Bo3'"""
    bo = _tag(e, "bo:")
    return join(short_comp(e.competition), _tag(e, "round:") or _tag(e, "stage:"),
                f"Bo{bo}" if bo else "")


def _cs2_actions(e: Event) -> list:
    acts = []
    if e.url and "hltv.org" not in e.url:
        acts.append(("Watch", e.url))
    acts.append(("HLTV", "https://www.hltv.org/matches"))
    return acts


def _cs2_watch(events, state, now) -> list[str]:
    """PandaScore ids of favourite matches that have started but whose result
    hasn't been sent: from this run's events, plus anything we reminded about
    in the last day (a finished match drops out of the upcoming list)."""
    ids = []
    for e in events:
        if "fav" in e.tags and e.id.startswith("cs2m-") and e.start <= now:
            ids.append(e.id[5:])
    cutoff = (now - timedelta(hours=24)).isoformat()
    for k, v in state.items():
        if k.startswith("fav-cs2m-") and v >= cutoff:
            ids.append(k[9:])
    return [i for i in dict.fromkeys(ids) if f"res-cs2-{i}" not in state]


def _watched(cfg, e: Event) -> bool:
    if e.sport == "liverpool":
        return True
    if e.sport == "cs2":
        return "fav" in e.tags and "match" in e.tags
    if e.sport == "f1":
        return _tag(e, "session:") in set(cfg.get("f1", {}).get("remind", ["Qualifying", "Sprint", "Race"]))
    return False


def _changes(cfg, events, state, now, tz) -> list:
    """Ping when a watched match/session moves by 15+ minutes, or Liverpool is postponed.
    The first time an event is seen its start time is just remembered (no alert)."""
    if not cfg.get("notifications", {}).get("time_changes", True):
        return []
    threshold = timedelta(minutes=cfg.get("notifications", {}).get("time_change_minutes", 15))
    fmt = lambda d: d.astimezone(tz).strftime("%a %d %b, %H:%M")
    sent = []
    for e in events:
        if not _watched(cfg, e):
            continue
        # Postponed / suspended (Liverpool)
        if "postponed" in e.tags:
            key = f"postponed-{e.id}"
            if key not in state and e.start > now - timedelta(days=1):
                if push(cfg, f"Postponed: {e.title}",
                        f"Was {fmt(e.start)} · new date TBC\n{short_comp(e.competition)}",
                        tags="warning", click=e.url, priority="high"):
                    state[key] = now.isoformat()
                    sent.append(key)
            continue
        key = f"start-{e.id}"
        if "live" in e.tags:               # already under way: the "Live now" ping covers it
            state[key] = e.start.isoformat()
            continue
        prev = state.get(key)
        state[key] = e.start.isoformat()
        if not prev:
            continue                                   # first sighting: just remember it
        old = datetime.fromisoformat(prev)
        if abs(e.start - old) < threshold or e.start < now - timedelta(minutes=30):
            continue
        later = e.start > old
        same_day = e.start.astimezone(tz).date() == old.astimezone(tz).date()
        new_t = f"{e.start.astimezone(tz):%H:%M}" if same_day else fmt(e.start)
        old_t = f"{old.astimezone(tz):%H:%M}" if same_day else fmt(old)
        if push(cfg, f"{'Delayed' if later else 'Moved earlier'}: {e.title}",
                f"Now {new_t} (was {old_t})\n{short_comp(e.competition)}",
                tags="alarm_clock", click=e.url, priority="high"):
            sent.append(f"moved-{e.id}")
        # A fresh reminder for the new time - unless it's within the hour, when
        # this "Delayed" ping already tells you the new time
        # (Liverpool always gets its kick-off ping, which carries the line-ups.)
        if e.sport == "liverpool" or e.start - now > timedelta(minutes=60):
            for prefix in ("ko-", "fav-", "f1-"):
                state.pop(f"{prefix}{e.id}", None)
        else:
            state.setdefault(f"fav-{e.id}" if e.sport == "cs2" else f"f1-{e.id}", now.isoformat())
    return sent


def _timing(cfg, state, now, local) -> list:
    """Log how long since the previous run, and warn (once a day) if runs stopped
    for a while - e.g. the 10-minute timer is down and only GitHub's slow
    hourly backup is running."""
    import os
    trigger = os.environ.get("GITHUB_EVENT_NAME", "local")
    prev = state.get("lastrun")
    state["lastrun"] = now.isoformat()
    if not prev:
        return []
    gap = now - datetime.fromisoformat(prev)
    mins = int(gap.total_seconds() // 60)
    print(f"Run timing: previous run {mins} min ago (started by: {trigger})")
    limit = timedelta(minutes=cfg.get("notifications", {}).get("max_gap_minutes", 35))
    key = f"gap-{local.date().isoformat()}"
    if gap > limit and key not in state:
        if push(cfg, "Alerts were paused",
                f"No check ran for {mins} min (until {local:%H:%M}), so some alerts may have been late.\n"
                "If this keeps happening, check the 10-minute timer on cron-job.org.",
                tags="warning"):
            state[key] = now.isoformat()
            return [key]
    return []


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
