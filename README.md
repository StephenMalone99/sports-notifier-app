# Sports Notifier

Push notifications and a local dashboard for upcoming sports events.

## Features

**Sports**
- **CS2:** top-tier tournaments and matches, plus selected teams at any event.
- **Football:** fixtures for a chosen club, with TV listings and line-ups.
- **Formula 1:** qualifying, sprint and race sessions.
- **PDC darts:** major events, with match-ups on event days.

**Notifications** (via [ntfy](https://ntfy.sh))
- Daily summary
- Reminders before events
- Delay, running-late and live alerts
- Results (optional)
- Health warnings

**Dashboard**
- Upcoming schedule, filterable by sport
- League tables, standings and rankings

## Setup

1. Get API keys from [PandaScore](https://pandascore.co), [football-data.org](https://www.football-data.org) and [SportsAPI Pro](https://sportsapipro.com) (optional).
2. Add these repository secrets: `PANDASCORE_TOKEN`, `FOOTBALL_DATA_TOKEN`, `SPORTSAPIPRO_KEY`, `NTFY_TOPIC`.
3. Subscribe to your topic in the ntfy app.
4. Trigger the `notify.yml` workflow on a schedule (e.g. via the `workflow_dispatch` API from an external scheduler).
5. Optional dashboard: run `set_keys.bat`, then `create_shortcut.bat`.

Settings are in `config.yaml`.
