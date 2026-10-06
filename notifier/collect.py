"""Fetch every source and save one combined, sorted list to data/events.json."""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .models import Event
from .sources import cs2, darts, liverpool

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "events.json"
SOURCES = {"cs2": cs2, "darts": darts, "liverpool": liverpool}

log = logging.getLogger("notifier")


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def collect(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=cfg.get("dashboard", {}).get("days_ahead", 60))
    events, status = [], {}
    for name, mod in SOURCES.items():
        try:
            got = mod.fetch(cfg.get(name, {}))
            status[name] = {"ok": True, "count": len(got)}
            events.extend(got)
        except Exception as exc:
            # Never echo request headers/URLs with keys — just the error type/message.
            msg = str(exc).split("?")[0][:200]
            status[name] = {"ok": False, "error": f"{type(exc).__name__}: {msg}"}
            log.warning("%s failed: %s", name, status[name]["error"])

    def still_relevant(e: Event):
        finish = e.end or (e.start + timedelta(hours=3))
        return finish >= now and e.start <= horizon

    events = sorted(filter(still_relevant, events), key=lambda e: e.start)
    payload = {
        "updated": now.isoformat(),
        "status": status,
        "events": [e.to_dict() for e in events],
    }
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_cached() -> dict | None:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    p = collect()
    for k, v in p["status"].items():
        print(f"{k:10} {'OK' if v['ok'] else 'FAILED'} {v.get('count', v.get('error'))}")
    print(f"{len(p['events'])} upcoming events saved to {CACHE}")
