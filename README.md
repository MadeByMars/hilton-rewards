# Hilton Award Finder

Small Python scraper for checking Hilton flexible-date award availability.
It is currently tuned for Conrad Bora Bora Nui (`PPTBNCI`), but the hotel code
can be changed in `SEARCHES`.

The script launches your local Google Chrome with a temporary Chrome DevTools
Protocol profile, opens Hilton's flexible-date calendar, captures the calendar
JSON responses, and prints reward availability for the configured target dates.

## Setup

Install the Python dependency:

```bash
python3 -m pip install -r requirements.txt
```

The script expects Google Chrome at:

```text
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
```

If Chrome is somewhere else, set `chrome_path` in a search config.

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

## Output

Generated files are intentionally ignored by git:

- `results/` contains parsed search output.
- `debug/` contains captured HTML, screenshots, response JSON, and diagnostics.
- Local Chrome/CDP profile folders are also ignored.

If Hilton changes the page or blocks a run, check the files in `debug/` for the
captured page state and network diagnostics.
