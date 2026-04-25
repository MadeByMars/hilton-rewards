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
        "arrival": "2026-09-01",
        "target_dates": ["2026-09-10", "2026-09-11"],
        "nights": 1,
        "adults": 1,
        "locale": "en",
        "standard_only": True,
        "standard_max_points": 200_000,
        "debug_dir": "debug",
        "timeout": 45,
        "cdp_user_data_dir": None,
        # Optional: set a stable label for output/debug artifact names.
        # "label": "pptbnci-sep10-1n",
    },
]
```

Notes:

- `arrival` anchors the Hilton flexible-date month that will be loaded.
- `target_dates` controls which dates are printed from that returned month.
- Leave `target_dates` empty to inspect the whole month.
- `standard_only=True` still prints all target dates, then summarizes standard
  room reward count and the lowest available reward.
- Multiple entries in `SEARCHES` run concurrently.
- Each search gets a unique generated label unless you provide `label`; debug
  artifacts use that label so searches for the same hotel/month do not overwrite
  each other.

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

The workflow sends email only when standard room rewards are found.

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
