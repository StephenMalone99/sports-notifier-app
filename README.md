# Sports Notifier

Phone alerts and a dashboard for the sport you follow, so you never miss a match.

Out of the box it tracks:

- **CS2:** top-tier events and their matches, with a star on your favourite teams wherever they play.
- **Liverpool FC:** every fixture, with TV channels and starting line-ups.
- **Formula 1:** qualifying, sprint and race times.
- **PDC darts:** the majors and Premier League nights, with match-ups and times on event days.

## Features

- **Morning summary:** one notification each day listing what's on: kick-off times, your teams' matches, F1 sessions, darts and streams.
- **Reminders:** about an hour before your favourite CS2 teams play, before Liverpool kick-off (with both starting line-ups), and before F1 qualifying and races.
- **Where to watch:** stream links for CS2 and TV channels for football and F1.
- **Results (optional):** full-time scores, series results and F1 podiums. Turn them off if you want to avoid spoilers.
- **Problem alerts:** a notification if a data source stops working.
- **Dashboard:** a page on your PC with everything coming up, filterable by sport.

Alerts run on GitHub Actions every hour, so they work even when your PC is off. Notifications are sent to your phone through the free [ntfy](https://ntfy.sh) app.

## Setting up your own copy

### 1. Get the free keys

| What | Where |
|---|---|
| PandaScore API token (CS2) | [pandascore.co](https://pandascore.co) → sign up → dashboard |
| football-data.org API token (football) | [football-data.org](https://www.football-data.org/client/register) |
| SportsAPI Pro key (darts match-ups, optional) | [sportsapipro.com](https://sportsapipro.com) → free plan (100 requests/day) |
| ntfy topic (your notification channel) | Make up a long, random name, e.g. `sports-x7k2p9q4`. Anyone who knows it can read your alerts. |

F1, the darts calendar and the line-up data don't need a key.

### 2. Phone

Install **ntfy** from the App Store or Play Store, tap **+**, and subscribe to your topic.

### 3. GitHub alerts

1. **Fork** this repository. A private copy is recommended.
2. Go to **Settings → Secrets and variables → Actions** and add three repository secrets:
   - `PANDASCORE_TOKEN`
   - `FOOTBALL_DATA_TOKEN`
   - `SPORTSAPIPRO_KEY` (optional, for darts match-ups)
   - `NTFY_TOPIC`
3. Open the **Actions** tab and enable workflows. Forks start with them turned off.
4. Click **Sports alerts → Run workflow** to test it. After that it runs every hour by itself.

### 4. Dashboard (optional, Windows)

1. Install [Python 3.12+](https://www.python.org/downloads/) and tick **"Add python.exe to PATH"**.
2. Run `set_keys.bat` and paste your keys when it asks.
3. Run `create_shortcut.bat` once, then open the dashboard from the **Sports Notifier** shortcut on your desktop.

The dashboard opens at `http://127.0.0.1:8000` and refreshes every few hours. Close its window to stop it.

## Making it yours

All settings are in **`config.yaml`**:

- **Favourite CS2 teams:** `cs2.favourite_teams`. Add any other names PandaScore uses for a team, e.g. `Team Falcons: [Falcons]`.
- **Which CS2 events count as top tier:** `cs2.always_include` / `exclude`.
- **Football TV channels:** `liverpool.tv`. Set these for your country.
- **F1 sessions and reminders:** `f1.sessions`, `f1.remind`. Add `Practice 1` etc. if you want them.
- **Results on or off:** `results.enabled`.
- **Timezone and morning summary time:** `timezone`, `notifications.daily_digest_hour`.

Darts dates are kept by hand in **`data/darts.yaml`**. Update them from the [PDC calendar](https://www.pdc.tv/calendar/) once a year; the app reminds you when they're running out.

Commit and push after changing anything, so the hourly alerts pick it up.

> **Following a different football team?** Change the team ids at the top of `notifier/sources/liverpool.py`: `FD_TEAM_ID` (football-data.org), `TSDB_TEAM_ID` (TheSportsDB) and `LIVERPOOL_ESPN_ID` in `notifier/lineups.py`.

## How it works

```
GitHub Actions (hourly) ─► notifier/collect.py ─► fetch CS2, football, F1, darts
                        └► notifier/notify.py  ─► decide what's due ─► ntfy ─► phone

Dashboard ─► app.py ─► same data ─► http://127.0.0.1:8000
```

Sent alerts are remembered in the Actions cache, so nothing is sent twice.

## Data sources

| Sport | Source | Key needed |
|---|---|---|
| CS2 | [PandaScore](https://pandascore.co) | Yes (free) |
| Football fixtures and results | [football-data.org](https://www.football-data.org), [TheSportsDB](https://www.thesportsdb.com) | Yes (free) / no |
| Football line-ups | ESPN public data (unofficial) | No |
| Formula 1 | [Jolpica F1 API](https://github.com/jolpica/jolpica-f1) | No |
| Darts calendar | `data/darts.yaml` (kept by hand) | No |
| Darts match-ups and times | [SportsAPI Pro](https://docs.sportsapipro.com) (only called on event days) | Yes (free) |
| Darts rankings | Wikipedia (PDC Order of Merit) | No |

Everything stays well within the free-plan limits. The hourly alerts use about half of GitHub's free Actions minutes for private repositories.

## Troubleshooting

- **No alerts:** open the latest run under **Actions**. The log shows each source as `OK` or `FAILED`.
- **Resend today's summary while testing:** delete the newest `sent-…` entry under **Actions → Caches**, then run the workflow.
- **Dashboard shows old data or an old layout:** close every dashboard window (or run `taskkill /im python.exe /f`), then reopen the shortcut.
