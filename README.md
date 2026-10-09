# Sports Notifier

Phone alerts and a dashboard for the sport I follow.

## What it does

**Tracks**
- **CS2:** top-tier events, every match, and my favourite teams wherever they play.
- **Liverpool FC:** every fixture, with TV channels and starting line-ups.
- **Formula 1:** qualifying, sprint and race times.
- **PDC darts:** the majors and Premier League nights, with match-ups on event days.

**Sends to my phone** (via the free [ntfy](https://ntfy.sh) app)
- A morning summary of what's on today.
- A reminder about an hour before matches, kick-offs and races.
- Delays, "running late" and "live now" for my teams' matches.
- Results after games (optional).
- A warning if something stops working.

**Dashboard on my PC**
- **Schedule:** everything coming up, filterable by sport.
- **Standings:** Premier League table, F1 standings, CS2 team form and the PDC rankings.

Alerts run on GitHub Actions every 10 minutes, so they work even when the PC is off.

## Setup

1. Get the free keys: [PandaScore](https://pandascore.co), [football-data.org](https://www.football-data.org), [SportsAPI Pro](https://sportsapipro.com) (optional).
2. Add them as repository secrets:
   - `PANDASCORE_TOKEN`
   - `FOOTBALL_DATA_TOKEN`
   - `SPORTSAPIPRO_KEY`
   - `NTFY_TOPIC`
3. Install ntfy on your phone and subscribe to your topic.
4. Make a free [cron-job.org](https://cron-job.org) job that starts the workflow every 10 minutes:
   - URL: `https://api.github.com/repos/<you>/<repo>/actions/workflows/notify.yml/dispatches`, method `POST`, body `{"ref":"main"}`
   - Headers: `Accept: application/vnd.github+json` and `Authorization: Bearer <token>` (a fine-grained token with **Actions: read and write** on this repo only)
5. **Dashboard (optional):** install Python, run `set_keys.bat`, then `create_shortcut.bat`.

Change teams, TV channels and other settings in `config.yaml`.
