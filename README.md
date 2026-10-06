# Sports Notifier

A personal app that keeps track of the sport I follow and sends alerts to my phone:

- **CS2:** top-tier tournaments, every match in them, and my favourite teams' matches at any event.
- **Liverpool FC:** every fixture, with likely TV channels and starting line-ups before kick-off.
- **PDC darts:** the majors and Premier League nights, where the big names play.

It has two parts:

1. **Phone alerts**, which run on GitHub every hour, even when my PC is off.
2. **A dashboard** on my PC that lists everything coming up.

---

## What it does

### Phone alerts (via the ntfy app)

| Alert | When | Example |
|---|---|---|
| **Morning summary** | Once a day, just after 9am, on days something is on | "Your teams" matches, Liverpool kick-off and TV, CS2 events with today's matches and streams, darts sessions, and what's coming tomorrow |
| **Favourite team reminder** | About an hour before Spirit, NAVI, FaZe, Vitality or Falcons play | `Team Spirit play in 50 min · Spirit vs 1WIN · ESL Pro League · BO3 · Watch: twitch.tv/eslcs` |
| **Liverpool kick-off** | About an hour before kick-off. It waits for the line-ups if they aren't out yet. | `Liverpool kick off in 55 min - line-ups in · TV: Sky Sports… · both starting XIs` |

Each alert is sent only once. Tapping a notification opens the stream or the fixture page.

### Dashboard (http://127.0.0.1:8000)

- **★ Your teams:** upcoming matches for your favourite teams.
- **On now / Today / Tomorrow / This week / Later:** everything else, grouped by date.
- A filter button for each sport, live countdowns, and a Refresh now button.
- It only works on this PC; other devices on the network can't open it.

---

## How it works

```
                ┌──────────────┐   PandaScore (CS2)
 GitHub Actions │  notifier/   │   football-data.org + TheSportsDB (Liverpool)
 every hour ───►│  collect.py  │◄─ ESPN (line-ups, match days only)
                │  notify.py   │   data/darts.yaml (darts, kept by hand)
                └──────┬───────┘
                       │ push
                       ▼
                 ntfy.sh ──► ntfy app on phone

 start_dashboard.bat ──► app.py (Flask) ──► same collect.py ──► browser
```

- `collect.py` fetches all sources and merges them into one list of events.
- `notify.py` decides what's due and sends it to ntfy. It records what it has sent in the GitHub Actions cache (`state/sent.json`) so nothing repeats.
- On Liverpool match days, the job keeps checking every 5 minutes until the line-ups are published, or until 40 minutes before kick-off.

---

## Data sources

| Sport | Source | Notes |
|---|---|---|
| CS2 | [PandaScore](https://pandascore.co) API (free plan) | Tournaments, matches and streams. PandaScore's tier labels aren't always right, so events named in `always_include` are always tracked. |
| Liverpool | [football-data.org](https://www.football-data.org) (free plan) | Premier League and Champions League fixtures |
| Liverpool | [TheSportsDB](https://www.thesportsdb.com) (public key) | Cup games that football-data doesn't cover |
| Liverpool | ESPN public API (unofficial) | Starting line-ups. If it fails, the alert is still sent without them. |
| Liverpool TV | `config.yaml` | Rule-based per competition (Ireland, 2026/27). There's no free listings source for the exact channel. |
| Darts | `data/darts.yaml` | Curated from the PDC calendar. Needs updating about once a year. |

**Free plan limits:** everything stays well under the limits.

- PandaScore: about 1% of the 1,000 requests/hour.
- football-data: 1 request per check.
- GitHub Actions: about 1,000 of the 2,000 free minutes a month (private repository).

---

## Project layout

```
NotifierApp/
├── .github/workflows/notify.yml   Hourly GitHub job
├── notifier/
│   ├── collect.py                 Fetches and merges all sources
│   ├── notify.py                  Builds and sends the alerts
│   ├── lineups.py                 Liverpool line-ups (ESPN)
│   ├── keystore.py / set_keys.py  Secure key storage
│   ├── models.py                  Event format shared by everything
│   └── sources/                   cs2.py · liverpool.py · darts.py
├── templates/index.html           Dashboard page
├── app.py                         Dashboard server
├── config.yaml                    All settings (no secrets)
├── data/darts.yaml                Darts calendar
├── set_keys.bat                   Saves API keys on this PC
└── start_dashboard.bat            Starts the dashboard
```

---

## Customising (`config.yaml`)

| Setting | What it does |
|---|---|
| `cs2.favourite_teams` | Your teams, plus any other names PandaScore uses for them, e.g. `Team Falcons: [Falcons]` |
| `cs2.always_include` / `exclude` | Event names that are always / never tracked |
| `cs2.remind_minutes_before` | How long before a favourite team's match to send the reminder |
| `liverpool.tv` | TV channels for each competition |
| `liverpool.lineups` | `true` waits for the line-ups and includes them; `false` sends the reminder straight away |
| `notifications.daily_digest_hour` | Hour the morning summary is sent |
| `timezone` | Timezone used for alert and dashboard times |

To change darts events, edit `data/darts.yaml`. Check it against [pdc.tv/calendar](https://www.pdc.tv/calendar/) when the new season is announced.

After editing, **commit and push in GitHub Desktop** so the phone alerts use the new settings. The dashboard picks changes up the next time you start it.

---

## Setup

### Keys and security

API keys are never stored in this folder, OneDrive or the code.

- **On this PC:** keys are saved in Windows Credential Manager by `set_keys.bat`.
- **On GitHub:** keys are repository secrets (**Settings → Secrets and variables → Actions**). Logs show them as `***`.

The three keys are `PANDASCORE_TOKEN`, `FOOTBALL_DATA_TOKEN` and `NTFY_TOPIC`. The ntfy topic works like a password: anyone who knows it can read your alerts.

If a key leaks, generate a new one on the provider's site and update it in both places.

### Phone

1. Install **ntfy** (by Philipp C. Heckel) from the Play Store or App Store.
2. Subscribe to your topic on `ntfy.sh`.

### Dashboard

1. Install **Python 3.14** from [python.org](https://www.python.org/downloads/windows/) and tick "Add python.exe to PATH".
2. Run `set_keys.bat` once to save your keys.
3. Run `start_dashboard.bat` whenever you want the dashboard. Close the black window to stop it.

### GitHub (phone alerts)

- The code is in the private repository **StephenMalone99/sports-notifier-app** and is pushed with GitHub Desktop.
- The workflow runs every hour by itself.
- To run it by hand: **Actions → Sports alerts → Run workflow**.

---

## Troubleshooting

| Problem | What to check |
|---|---|
| No alerts | Open the latest run under **Actions**. In the "Fetch events and send alerts" step, each source should show `OK`. |
| Want to resend today's summary for testing | **Actions → Caches**, delete the newest `sent-…` entry, then run the workflow. |
| A CS2 event is missing | The run log lists every event it skipped and why. Add the event's name to `always_include`. |
| A favourite team isn't picked up | Check the name PandaScore uses in the log and add it as an alias. |
| The Liverpool alert has no line-ups | Look in the log for lines starting with `Line-ups`. The ESPN source is unofficial and may have changed. |
| The dashboard won't start | Make sure Python is installed with PATH ticked, then delete `%LOCALAPPDATA%\NotifierApp\venv` and run the `.bat` again. |
