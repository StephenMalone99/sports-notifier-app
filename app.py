"""Local dashboard: http://127.0.0.1:8000

Only listens on your own PC (127.0.0.1), so nothing on your network or the
internet can reach it. Re-fetches data every few hours in the background.
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, redirect, render_template, url_for

from notifier.collect import collect, load_cached, load_config
from notifier.models import Event

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True   # page design changes show on browser refresh
cfg = load_config()
TZ = ZoneInfo(cfg.get("timezone", "Europe/Dublin"))
_lock = threading.Lock()
_last_manual = 0.0


def refresh():
    with _lock:
        collect(cfg)


def background():
    hours = cfg.get("dashboard", {}).get("refresh_hours", 3)
    while True:
        try:
            refresh()
        except Exception as exc:
            logging.warning("refresh failed: %s", exc)
        time.sleep(hours * 3600)


def bucket(e: Event, now_local):
    s = e.start.astimezone(TZ)
    end = (e.end or e.start).astimezone(TZ)
    today = now_local.date()
    if s.date() <= today <= end.date():
        return "Today" if s.date() == today or not e.all_day else "On now"
    if s.date() == today + timedelta(days=1):
        return "Tomorrow"
    if s.date() <= today + timedelta(days=7):
        return "This week"
    return "Later"


@app.template_filter("local")
def local(dt, fmt="%a %d %b, %H:%M"):
    return dt.astimezone(TZ).strftime(fmt)


@app.route("/")
def index():
    data = load_cached() or {"events": [], "status": {}, "updated": None}
    now_local = datetime.now(TZ)
    order = ["On now", "Today", "Tomorrow", "This week", "Later"]
    groups = {k: [] for k in order}
    yourteams = []
    f1_events = []
    for d in data["events"]:
        e = Event.from_dict(d)
        b = bucket(e, now_local)
        if e.sport == "f1":
            f1_events.append(e)              # F1 gets its own section, grouped by weekend
            continue
        if "match" in e.tags:
            if "fav" in e.tags:
                yourteams.append(e)          # favourites get their own section
                continue
            elif b not in ("Today", "Tomorrow", "On now"):
                continue                     # later CS2 matches: the event card covers them
        groups[b].append(e)
    # One card per Grand Prix weekend, next few only
    weekends = {}
    for e in f1_events:
        weekends.setdefault(e.title.split(" - ")[0], []).append(e)
    now_utc = datetime.now(timezone.utc)
    f1 = []
    for gp, sessions in weekends.items():
        sessions.sort(key=lambda x: x.start)
        if sessions[-1].start + timedelta(hours=3) < now_utc:
            continue
        nxt = next((x for x in sessions if x.start + timedelta(hours=2) > now_utc), sessions[-1])
        f1.append({"name": gp, "sessions": sessions, "next": nxt, "first": sessions[0]})
    f1.sort(key=lambda w: w["next"].start)
    f1 = f1[: cfg.get("dashboard", {}).get("f1_weekends", 4)]
    updated = datetime.fromisoformat(data["updated"]) if data.get("updated") else None
    return render_template("index.html", groups=groups, yourteams=yourteams, f1=f1,
                           status=data.get("status", {}),
                           updated=updated, now=datetime.now(timezone.utc))


@app.post("/refresh")
def manual_refresh():
    global _last_manual
    if time.time() - _last_manual > 300:  # at most every 5 min, protects API limits
        _last_manual = time.time()
        refresh()
    return redirect(url_for("index"))


@app.get("/api/events")
def api_events():
    return jsonify(load_cached() or {})


def _port_in_use(port=8000) -> bool:
    import socket
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    if _port_in_use():
        print("The dashboard is already running in another window.")
        print("To restart it with the latest code, close that window first, then open the shortcut again.")
        input("Press Enter to close...")
        raise SystemExit
    threading.Thread(target=background, daemon=True).start()
    app.run(host="127.0.0.1", port=8000, debug=False)
