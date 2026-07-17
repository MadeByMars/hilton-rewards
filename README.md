# Hilton Award Finder

Small Python scraper for checking Hilton flexible-date award availability.
It is currently tuned for Conrad Bora Bora Nui (`PPTBNCI`), but the hotel code
can be changed in `SEARCHES`.

The script launches Google Chrome with a temporary Chrome DevTools Protocol
profile, opens Hilton's flexible-date calendar, captures the calendar JSON
responses, and prints reward availability for the configured target dates.

## Setup

Install the Python dependency:

```bash
python3 -m pip install -r requirements.txt
```

Locally, the script looks for Google Chrome at:

```text
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

It also checks common Linux Chrome/Chromium paths and the `CHROME_PATH`
environment variable. If Chrome is somewhere else, set `chrome_path` in a
search config.

## Configure Searches

Edit `SEARCHES` in `hilton_award_finder.py`.

Example:

```python
SEARCHES = [
    {
        "hotel": "PPTBNCI",
        "arrival": "2026-09-05",
        "target_dates": ["2026-09-05"],
        "nights": 5,
        "adults": 1,
        "locale": "en",
        "standard_only": True,
        "standard_max_points": 200_000,
        "debug_dir": "debug",
        "timeout": 45,
        "cdp_user_data_dir": None,
        # Optional: set a stable label for output/debug artifact names.
        "label": "pptbnci-2026-09-05-5n",
    },
]
```

Notes:

- `arrival` anchors the Hilton flexible-date month that will be loaded.
- `target_dates` controls which dates are printed from that returned month.
- For an exact 5-night stay from 2026-09-05 to 2026-09-10, use
  `arrival="2026-09-05"`, `nights=5`, and `target_dates=["2026-09-05"]`.
- Leave `target_dates` empty to inspect the whole month.
- `standard_only=True` still prints all target dates, then summarizes standard
  room reward count and the lowest available reward.
- Multiple entries in `SEARCHES` run sequentially by default for Chrome/CDP
  reliability. Increase `MAX_CONCURRENT_SEARCHES` only if your environment can
  launch multiple Chrome instances cleanly.
- Each search gets a unique generated label unless you provide `label`; debug
  artifacts use that label so searches for the same hotel/month do not overwrite
  each other.
- Use `alert_group` and `alert_required_dates` when an email should only be sent
  after a full set of dates is available. The LIRGUWA holiday search uses this
  because the 2026-12-28 to 2027-01-02 stay crosses a month boundary and must be
  split into December and January flexible-date searches.

## Current Searches

- `PPTBNCI`: Conrad Bora Bora Nui, 5-night stay from 2026-09-05 to 2026-09-10.
- `LIRGUWA`: Waldorf Astoria Costa Rica Punta Cacique, one-night standard reward
  checks for 2026-12-28, 2026-12-29, 2026-12-30, 2026-12-31, and 2027-01-01.
  Email notification is sent only if all five required nights are standard
  rewards.

## Run

```bash
python3 hilton_award_finder.py
```

The script prints a table for each configured search and writes parsed JSON to
`results/`.

## GitHub Actions

The workflow in `.github/workflows/hilton.yml` runs the search automatically
every 30 minutes and can also be triggered manually from the GitHub Actions UI.

### Enable Actions

1. Open the repo on GitHub.
2. Go to **Actions**.
3. Enable workflows if GitHub asks for confirmation.

### Email Notifications

The workflow sends email when an alert condition is met. Standalone searches
alert when a configured target date has a standard reward. Grouped searches,
such as the LIRGUWA holiday search, alert only when all required dates in the
group have standard rewards.

Add these repository secrets under **Settings** -> **Secrets and variables** ->
**Actions**:

- `EMAIL_USERNAME`: Gmail address used to send email.
- `EMAIL_PASSWORD`: Gmail app password.
- `EMAIL_TO`: optional recipient address. If omitted, `EMAIL_USERNAME` is used.

Manual run:

```text
Actions -> Hilton Reward Search -> Run workflow
```

The workflow uploads `results/` and `debug/` as a run artifact for inspection.

GitHub-hosted runners use data-center IPs, so Hilton may occasionally block or
challenge a run even when the local script works. Check the uploaded debug
artifact if a scheduled run captures no rewards.

## Output

Generated files are intentionally ignored by git:

- `results/` contains parsed search output.
- `debug/` contains captured HTML, screenshots, response JSON, and diagnostics.
- Local Chrome/CDP profile folders are also ignored.

If Hilton changes the page or blocks a run, check the files in `debug/` for the
captured page state and network diagnostics.

## Project Structure

```text
.
├── hilton_award_finder.py          # Main scraper script
├── requirements.txt                # Python dependencies
├── README.md
├── .gitignore
├── .github/
│   ├── workflows/
│   │   └── hilton.yml              # Scheduled/manual GitHub Actions workflow
│   └── scripts/
│       └── summarize.py            # Workflow result summary and email body
├── results/                        # Generated parsed output, ignored by git
└── debug/                          # Generated diagnostics, ignored by git
```
