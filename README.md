# Sports Notifier

Tracks **CS2 S-tier tournaments**, **PDC darts majors** and **Liverpool FC fixtures**.

- **Dashboard** on your PC: `start_dashboard.bat` → http://127.0.0.1:8000
- **Phone alerts** from GitHub Actions every hour, even when your PC is off: a morning digest of what's on today and a ping 60 minutes before Liverpool kick-off.

## Keeping the API keys safe

Keys are never written into this folder, so they can't end up in OneDrive or GitHub.

| Where it runs | Where the keys live |
|---|---|
| Your PC | Windows Credential Manager, encrypted with your Windows login. Saved with `set_keys.bat` (typing is hidden). |
| GitHub Actions | Repository **Secrets**, encrypted by GitHub, write-only once saved and shown as `***` in logs. |

Other safeguards:
- The repo should be **private**. `.gitignore` blocks `.env`, key files, cached data and alert state.
- The dashboard only listens on `127.0.0.1`, so other devices on your network can't open it.
- The workflow has read-only permissions and doesn't keep GitHub credentials after checkout.
- Error messages never print keys or request URLs.
- **Don't paste keys into chats, screenshots, issues or code.** If one leaks, regenerate it on the provider's site and save the new one with `set_keys.bat` and in GitHub Secrets.
- Turn on two-factor authentication for GitHub, PandaScore and football-data.org.
- Your ntfy topic name works like a password, because anyone who knows it can read your alerts. Use the random one `set_keys.bat` suggests.

## Setup

### 1. On your PC
1. Install **Python 3.12** from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
2. Double-click **`set_keys.bat`**. Paste each key (it stays hidden) and accept the suggested ntfy topic. Write the topic down; you'll need it in steps 2 and 3.
3. Double-click **`start_dashboard.bat`**. The first run takes a minute while it installs.

### 2. Phone
Install the **ntfy** app (Android/iOS), tap **+**, and subscribe to your topic on `ntfy.sh`.

### 3. GitHub (alerts while your PC is off)
1. Create a **private** repository, e.g. `sports-notifier`.
2. Upload this folder with GitHub Desktop (*File → Add local repository*, then *Publish*, keeping "private" ticked). `.gitignore` keeps local data out.
3. In the repo, open **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `PANDASCORE_TOKEN`
   - `FOOTBALL_DATA_TOKEN`
   - `NTFY_TOPIC`
4. Open **Actions → Sports alerts → Run workflow** to test it. After that it runs every hour.

Free-plan usage: about 730 Action minutes a month, well inside GitHub's 2,000 free minutes for private repos.

## Customising
- `config.yaml`: CS2 tiers (add `a` for more events), reminder timing, digest hour, timezone.
- `data/darts.yaml`: darts dates. Check them against https://www.pdc.tv/calendar/ each year.

## Data sources
- CS2: PandaScore API (free plan). HLTV has no official API.
- Liverpool: football-data.org (Premier League + Champions League) and TheSportsDB (cup games).
- Darts: curated list of PDC majors and Premier League dates.
