#!/usr/bin/env python3
"""
Hilton flexible-date award availability scraper.

Fetches Hilton Honors flexible-date results for a hotel and reports dates that
look like standard room rewards. It launches local Chrome with a temporary
remote-debugging profile, then connects through CDP to capture Hilton's
calendar JSON from a real browser session.

Example:
    Edit SEARCHES below, then run:
    python3 hilton_award_finder.py
"""

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.parse import urlencode
from urllib.request import urlopen

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


RESULTS_DIR = "results"
DEFAULT_HOTEL = "PPTBNCI"
DEFAULT_STANDARD_MAX_POINTS = 120_000
DEFAULT_DEBUG_DIR = "debug"


def detect_chrome_path() -> str:
    env_path = os.environ.get("CHROME_PATH")
    if env_path:
        return env_path

    known_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for path in known_paths:
        if os.path.exists(path):
            return path

    for executable in (
        "google-chrome",
        "google-chrome-stable",
        "chrome",
        "chromium",
        "chromium-browser",
    ):
        path = shutil.which(executable)
        if path:
            return path

    return known_paths[0]


DEFAULT_CHROME_PATH = detect_chrome_path()

os.environ.setdefault("NODE_NO_WARNINGS", "1")


RUN_CDP_SEARCHES = True
CDP_USER_DATA_DIR = None


# Define searches here. Each configured search runs concurrently.
SEARCHES = [
    {
        "hotel": "PPTBNCI",
        # Hilton flexible dates returns availability for the month containing
        # this arrival date.
        "arrival": "2026-09-01",
        # Leave empty to inspect the whole returned month.
        "target_dates": ["2026-09-10", "2026-09-11"],
        "nights": 1,
        "adults": 1,
        "locale": "en",
        "standard_only": True,
        "standard_max_points": 200_000,
        "debug_dir": DEFAULT_DEBUG_DIR,
        "timeout": 45,
        # Leave as None for a fresh temporary Chrome profile on each run.
        "cdp_user_data_dir": CDP_USER_DATA_DIR,
    },
    {
        "hotel": "PPTBNCI",
        # Hilton flexible dates returns availability for the month containing
        # this arrival date.
        "arrival": "2026-09-01",
        # Leave empty to inspect the whole returned month.
        "target_dates": ["2026-09-10"],
        "nights": 2,
        "adults": 1,
        "locale": "en",
        "standard_only": True,
        "standard_max_points": 200_000,
        "debug_dir": DEFAULT_DEBUG_DIR,
        "timeout": 45,
        # Leave as None for a fresh temporary Chrome profile on each run.
        "cdp_user_data_dir": CDP_USER_DATA_DIR,
    },
    # Add more searches, for example:
    # {
    #     "hotel": "PPTBNCI",
    #     "arrival": "2026-10-01",
    #     "nights": 3,
    #     "adults": 2,
    #     "standard_only": True,
    # },
]


@dataclass
class HiltonSearchParams:
    hotel_code: str = DEFAULT_HOTEL
    arrival_date: str = "2026-09-01"
    nights: int = 1
    adults: int = 1
    redeem_points: bool = True
    locale: str = "en"

    @property
    def departure_date(self) -> str:
        arrival = datetime.strptime(self.arrival_date, "%Y-%m-%d").date()
        return (arrival + timedelta(days=self.nights)).isoformat()

    def to_url(self) -> str:
        params = {
            "ctyhocn": self.hotel_code,
            "arrivalDate": self.arrival_date,
            "departureDate": self.departure_date,
            "redeemPts": str(self.redeem_points).lower(),
            "room1NumAdults": self.adults,
        }
        base_url = f"https://www.hilton.com/{self.locale}/book/reservation/flexibledates/"
        return f"{base_url}?{urlencode(params)}"


@dataclass
class RewardNight:
    date: str
    points: Optional[int] = None
    available: bool = False
    standard: bool = False
    room_name: Optional[str] = None
    reward_type: Optional[str] = None
    source: str = "unknown"
    raw_text: Optional[str] = None

    def display_points(self) -> str:
        return f"{self.points:,}" if self.points is not None else "-"


@dataclass
class HiltonSearchResult:
    hotel_code: str
    arrival_date: str
    nights: int
    url: str
    target_dates: list[str] = field(default_factory=list)
    rewards: list[RewardNight] = field(default_factory=list)
    raw_response_count: int = 0
    response_log: list[dict[str, Any]] = field(default_factory=list)
    search_label: Optional[str] = None
    debug_prefix: Optional[str] = None
    page_title: Optional[str] = None
    error: Optional[str] = None
    main_response_status: Optional[int] = None
    main_response_url: Optional[str] = None
    main_response_headers: dict[str, str] = field(default_factory=dict)
    main_request_headers: dict[str, str] = field(default_factory=dict)
    browser_user_agent: Optional[str] = None
    browser_user_agent_data: dict[str, Any] = field(default_factory=dict)
    page_reference: Optional[str] = None
    akamai_challenge_detected: bool = False
    headless_chrome_detected: bool = False

    def rewards_for_dates(
        self, target_dates: Optional[list[str]] = None
    ) -> list[RewardNight]:
        dates = target_dates if target_dates is not None else self.target_dates
        if not dates:
            return self.rewards
        target_set = set(dates)
        return [reward for reward in self.rewards if reward.date in target_set]

    def standard_rewards(
        self, target_dates: Optional[list[str]] = None
    ) -> list[RewardNight]:
        return [
            reward
            for reward in self.rewards_for_dates(target_dates)
            if reward.available and reward.standard
        ]

    def print_table(
        self,
        standard_only: bool = False,
        target_dates: Optional[list[str]] = None,
    ) -> None:
        dates = target_dates if target_dates is not None else self.target_dates
        scoped_rewards = sorted(
            self.rewards_for_dates(dates),
            key=lambda reward: (reward.date, reward.points or 0),
        )
        rewards = scoped_rewards
        if standard_only and not dates:
            rewards = sorted(
                self.standard_rewards(dates),
                key=lambda reward: (reward.date, reward.points or 0),
            )
        missing_dates = sorted(set(dates or []) - {reward.date for reward in scoped_rewards})
        available_rewards = [reward for reward in scoped_rewards if reward.available]
        standard_rewards = [
            reward for reward in scoped_rewards if reward.available and reward.standard
        ]

        print(f"\n{'=' * 72}")
        print(f"  Hilton {self.hotel_code} | {self.arrival_date} | {self.nights} night(s)")
        if dates:
            print(f"  Target dates: {', '.join(dates)}")
        print(f"{'=' * 72}")
        print(f"{'Date':<12} {'Points':>10} {'Type':<18} {'Status':<12} Source")
        print(f"{'-' * 12} {'-' * 10} {'-' * 18} {'-' * 12} {'-' * 10}")

        if not rewards:
            message = (
                "No standard room rewards found."
                if standard_only
                else "No matching reward nights found."
            )
            print(message)
        else:
            for reward in rewards:
                reward_type = reward.reward_type or (
                    "Standard" if reward.standard else "Unknown"
                )
                status = "Available" if reward.available else "N/A"
                print(
                    f"{reward.date:<12} {reward.display_points():>10} "
                    f"{reward_type:<18} {status:<12} {reward.source}"
                )

        print(f"\nParsed reward nights: {len(scoped_rewards)}")
        print(f"Available: {len(available_rewards)}/{len(scoped_rewards)}")
        if standard_only:
            print(f"Standard room rewards: {len(standard_rewards)}")
            if not standard_rewards and scoped_rewards:
                print("No standard room rewards found.")
        if available_rewards:
            best = min(
                available_rewards,
                key=lambda reward: reward.points or float("inf"),
            )
            print(
                f"Lowest available reward: {best.display_points()} points "
                f"({best.reward_type or 'Unknown'}) on {best.date}"
            )
        if missing_dates:
            print(f"No calendar data for: {', '.join(missing_dates)}")


def parse_points(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value)
    match = re.search(r"(\d[\d,\.]*)\s*(?:points|pts|pt)?", text, re.IGNORECASE)
    if not match:
        return None

    digits = re.sub(r"[^\d]", "", match.group(1))
    return int(digits) if digits else None


def parse_date(value: Any, default_year: int) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()

    text = str(value)
    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso_match:
        return iso_match.group(1)

    slash_match = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
    if slash_match:
        month, day, year = slash_match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    month_match = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|"
        r"Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})(?:,\s*(20\d{2}))?\b",
        text,
        re.IGNORECASE,
    )
    if month_match:
        month_name, day, year = month_match.groups()
        month = datetime.strptime(month_name[:3].title(), "%b").month
        return f"{int(year or default_year):04d}-{month:02d}-{int(day):02d}"

    return None


def looks_standard_reward(text: str, points: Optional[int], standard_max_points: int) -> bool:
    lowered = text.lower()
    if "premium room reward" in lowered:
        return False
    if "standard room reward" in lowered:
        return True
    return points is not None and points <= standard_max_points


def extract_rewards_from_shop_calendar(
    payload: Any,
    standard_max_points: int,
) -> list[RewardNight]:
    rewards: list[RewardNight] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            calendar_avail = node.get("shopCalendarAvail")
            if isinstance(calendar_avail, dict):
                calendars = calendar_avail.get("calendars") or []
                for calendar in calendars:
                    if not isinstance(calendar, dict):
                        continue
                    room_rate = calendar.get("roomRate") or {}
                    rate_plan = room_rate.get("ratePlan") or {}
                    points = parse_points(
                        room_rate.get("dailyRmPointsRate")
                        or room_rate.get("dailyRmPointsRateFmt")
                    )
                    reward_date = parse_date(calendar.get("arrivalDate"), 2000)
                    if not reward_date:
                        continue

                    reward_type = rate_plan.get("ratePlanName")
                    room_type = room_rate.get("roomTypeCode")
                    text = " ".join(
                        str(value)
                        for value in (
                            reward_type,
                            rate_plan.get("ratePlanDesc"),
                            room_rate.get("ratePlanCode"),
                            room_type,
                        )
                        if value
                    )
                    rewards.append(
                        RewardNight(
                            date=reward_date,
                            points=points,
                            available=points is not None
                            and room_rate.get("numRoomsAvail", 0) > 0,
                            standard=looks_standard_reward(
                                text, points, standard_max_points
                            ),
                            room_name=room_type,
                            reward_type=reward_type,
                            source="shopCalendarAvail",
                            raw_text=text[:500],
                        )
                    )

            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return rewards


def extract_rewards_from_json(
    payload: Any,
    default_year: int,
    standard_max_points: int,
) -> list[RewardNight]:
    rewards: list[RewardNight] = extract_rewards_from_shop_calendar(
        payload, standard_max_points
    )

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            text_blob = " ".join(str(value) for value in node.values() if value is not None)
            points = None
            reward_date = None
            room_name = None
            reward_type = None

            for key, value in node.items():
                lowered_key = key.lower()
                if reward_date is None and any(
                    token in lowered_key for token in ("date", "arrival", "checkin")
                ):
                    reward_date = parse_date(value, default_year)
                if points is None and any(
                    token in lowered_key
                    for token in ("point", "honors", "rateamount", "amount")
                ):
                    points = parse_points(value)
                if room_name is None and any(token in lowered_key for token in ("room", "name")):
                    room_name = str(value) if value is not None else None
                if reward_type is None and any(
                    token in lowered_key for token in ("reward", "rateplan", "rateplanname")
                ):
                    reward_type = str(value) if value is not None else None

            if reward_date and points:
                available = "unavailable" not in text_blob.lower()
                standard = looks_standard_reward(text_blob, points, standard_max_points)
                rewards.append(
                    RewardNight(
                        date=reward_date,
                        points=points,
                        available=available,
                        standard=standard,
                        room_name=room_name,
                        reward_type=reward_type,
                        source="json",
                        raw_text=text_blob[:500],
                    )
                )

            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return rewards


def merge_rewards(rewards: list[RewardNight]) -> list[RewardNight]:
    merged: dict[tuple[str, Optional[int], str], RewardNight] = {}
    for reward in rewards:
        key = (reward.date, reward.points, reward.reward_type or "")
        existing = merged.get(key)
        if not existing:
            merged[key] = reward
            continue

        existing.available = existing.available or reward.available
        existing.standard = existing.standard or reward.standard
        existing.room_name = existing.room_name or reward.room_name
        existing.reward_type = existing.reward_type or reward.reward_type
        if reward.source not in existing.source:
            existing.source = f"{existing.source},{reward.source}"

    return sorted(merged.values(), key=lambda reward: (reward.date, reward.points or 0))


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def process_output_tail(process: subprocess.Popen, limit: int = 2000) -> str:
    try:
        stdout, stderr = process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        return ""
    output = "\n".join(part for part in (stdout, stderr) if part)
    return output[-limit:]


def wait_for_cdp(
    port: int, process: subprocess.Popen, timeout_seconds: int
) -> None:
    deadline = time.time() + timeout_seconds
    url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        if process.poll() is not None:
            details = process_output_tail(process)
            message = f"Chrome exited before DevTools started on port {port}."
            if details:
                message = f"{message}\n{details}"
            raise RuntimeError(message)
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise TimeoutError(
        f"Chrome DevTools did not start on port {port}. "
        "If a Chrome window stayed open, close it and run again."
    )


def diagnostic_headers(headers: dict[str, str]) -> dict[str, str]:
    useful_keys = {
        "accept",
        "accept-ch",
        "accept-language",
        "cache-control",
        "content-type",
        "date",
        "referer",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "sec-fetch-dest",
        "sec-fetch-mode",
        "sec-fetch-site",
        "sec-fetch-user",
        "server",
        "set-cookie",
        "strict-transport-security",
        "upgrade-insecure-requests",
        "user-agent",
        "vary",
        "x-akamai-transformed",
        "x-cache",
        "x-cdn",
        "x-frame-options",
        "x-request-id",
    }
    return {
        key: value
        for key, value in headers.items()
        if key.lower() in useful_keys and key.lower() not in {"cookie", "set-cookie"}
    }


def parse_page_reference(page_text: str) -> Optional[str]:
    match = re.search(r"Reference No\.\s*([A-Za-z0-9.\-]+)", page_text)
    return match.group(1) if match else None


def safe_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return cleaned or "search"


def build_search_label(
    params: HiltonSearchParams,
    target_dates: Optional[list[str]] = None,
) -> str:
    if target_dates:
        date_part = "_".join(date.replace("-", "") for date in target_dates)
        if len(date_part) > 80:
            date_part = f"{len(target_dates)}dates"
    else:
        date_part = "all-dates"
    return safe_filename_part(
        f"{params.hotel_code}-{params.arrival_date}-{params.nights}n-"
        f"{params.adults}a-{date_part}"
    )


async def fetch_hilton_rewards_cdp(
    params: HiltonSearchParams,
    standard_max_points: int = DEFAULT_STANDARD_MAX_POINTS,
    debug_dir: Optional[str] = None,
    timeout_seconds: int = 60,
    chrome_path: str = DEFAULT_CHROME_PATH,
    user_data_dir: Optional[str] = CDP_USER_DATA_DIR,
    debug_label: Optional[str] = None,
    window_index: int = 0,
) -> HiltonSearchResult:
    url = params.to_url()
    default_year = int(params.arrival_date[:4])
    all_rewards: list[RewardNight] = []
    raw_responses: list[dict[str, Any]] = []
    response_log: list[dict[str, Any]] = []

    result = HiltonSearchResult(
        hotel_code=params.hotel_code,
        arrival_date=params.arrival_date,
        nights=params.nights,
        url=url,
        search_label=debug_label,
    )

    if not os.path.exists(chrome_path):
        result.error = f"Chrome executable not found: {chrome_path}"
        return result

    created_temp_profile = user_data_dir is None
    profile_dir = user_data_dir or tempfile.mkdtemp(prefix="hilton-cdp-")
    os.makedirs(profile_dir, exist_ok=True)
    port = find_free_port()
    command = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={os.path.abspath(profile_dir)}",
        "--new-window",
        "--window-size=1360,1000",
        f"--window-position={40 + (window_index * 90)},{40 + (window_index * 60)}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if os.environ.get("CI"):
        command.extend(
            [
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-sandbox",
            ]
        )
    command.append("about:blank")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        wait_for_cdp(port, process=process, timeout_seconds=10)

        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}"
            )
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = await context.new_page()

            async def handle_response(response) -> None:
                parsed_url = urlparse(response.url)
                host = parsed_url.netloc.lower()
                if "hilton" in host or "akamai" in host or response.url.startswith(url):
                    response_log.append(
                        {
                            "status": response.status,
                            "url": response.url,
                            "content_type": response.headers.get("content-type", ""),
                        }
                    )

                content_type = response.headers.get("content-type", "")
                if "application/json" not in content_type:
                    return
                path = parsed_url.path.lower()
                if not (
                    host.endswith("hilton.com")
                    or host.endswith("hilton.io")
                    or "graphql" in path
                    or "reservation" in path
                ):
                    return
                try:
                    payload = await response.json()
                except Exception:
                    return
                raw_responses.append({"url": response.url, "data": payload})
                all_rewards.extend(
                    extract_rewards_from_json(
                        payload, default_year, standard_max_points
                    )
                )

            page.on("response", handle_response)

            main_response = await page.goto(
                url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000
            )
            if main_response:
                result.main_response_status = main_response.status
                result.main_response_url = main_response.url
                result.main_response_headers = diagnostic_headers(main_response.headers)
                result.main_request_headers = diagnostic_headers(
                    await main_response.request.all_headers()
                )

            try:
                await page.wait_for_load_state("networkidle", timeout=timeout_seconds * 1000)
            except PlaywrightTimeoutError:
                pass

            # Akamai sometimes does an initial browser challenge and then reloads.
            # Give the real Chrome profile a short window to settle and emit GraphQL.
            deadline = time.time() + timeout_seconds
            while time.time() < deadline and not all_rewards:
                await page.wait_for_timeout(1000)
                try:
                    title = await page.title()
                except Exception:
                    continue
                if title == "Hilton Page Reference Code":
                    break

            for _ in range(3):
                try:
                    result.page_title = await page.title()
                    result.browser_user_agent = await page.evaluate("navigator.userAgent")
                    result.browser_user_agent_data = await page.evaluate(
                        """async () => {
                            if (!navigator.userAgentData) return {};
                            return await navigator.userAgentData.getHighEntropyValues([
                                'architecture',
                                'bitness',
                                'brands',
                                'fullVersionList',
                                'mobile',
                                'model',
                                'platform',
                                'platformVersion',
                                'uaFullVersion',
                                'wow64'
                            ]);
                        }"""
                    )
                    page_text = await page.locator("body").inner_text(timeout=3000)
                    page_html = await page.content()
                    break
                except Exception:
                    await page.wait_for_timeout(1000)
            else:
                page_text = ""
                page_html = ""
            result.page_reference = parse_page_reference(page_text)
            result.akamai_challenge_detected = (
                "sec-if-cpt-container" in page_html
                or "Powered and protected by" in page_html
                or "/.well-known/sbsd/" in page_html
            )
            result.headless_chrome_detected = "HeadlessChrome" in page_html

            if (
                not all_rewards
                and (
                    result.page_title == "Hilton Page Reference Code"
                    or "SOMETHING WENT WRONG" in page_text
                    or result.akamai_challenge_detected
                )
            ):
                if result.akamai_challenge_detected:
                    result.error = (
                        "Hilton/Akamai returned a browser challenge before "
                        "the flexible-date calendar loaded."
                    )
                else:
                    result.error = (
                        "Hilton returned its Page Reference Code error page before "
                        "the flexible-date calendar loaded."
                    )

            if debug_dir:
                os.makedirs(debug_dir, exist_ok=True)
                artifact_label = debug_label or build_search_label(params)
                prefix = os.path.join(debug_dir, f"{safe_filename_part(artifact_label)}-cdp")
                result.debug_prefix = prefix
                with open(f"{prefix}.html", "w", encoding="utf-8") as file:
                    file.write(page_html)
                await page.screenshot(path=f"{prefix}.png", full_page=True)
                with open(f"{prefix}-responses.json", "w", encoding="utf-8") as file:
                    json.dump(raw_responses, file, indent=2, default=str)
                with open(f"{prefix}-diagnostics.json", "w", encoding="utf-8") as file:
                    json.dump(
                        {
                            "main_response_status": result.main_response_status,
                            "main_response_url": result.main_response_url,
                            "main_response_headers": result.main_response_headers,
                            "main_request_headers": result.main_request_headers,
                            "response_log": response_log,
                            "browser_user_agent": result.browser_user_agent,
                            "browser_user_agent_data": result.browser_user_agent_data,
                            "page_title": result.page_title,
                            "page_reference": result.page_reference,
                            "akamai_challenge_detected": result.akamai_challenge_detected,
                            "headless_chrome_detected": result.headless_chrome_detected,
                        },
                        file,
                        indent=2,
                    )

            await browser.close()

    except Exception as exc:
        result.error = str(exc)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        if created_temp_profile:
            shutil.rmtree(profile_dir, ignore_errors=True)

    result.raw_response_count = len(raw_responses)
    result.response_log = response_log
    result.rewards = merge_rewards(all_rewards)
    return result


async def run_cdp_search(
    search: dict[str, Any],
    search_index: int = 0,
) -> HiltonSearchResult:
    params = HiltonSearchParams(
        hotel_code=search.get("hotel", DEFAULT_HOTEL),
        arrival_date=search["arrival"],
        nights=search.get("nights", 1),
        adults=search.get("adults", 1),
        locale=search.get("locale", "en"),
    )
    target_dates = search.get("target_dates", [])
    search_label = search.get("label") or build_search_label(params, target_dates)
    result = await fetch_hilton_rewards_cdp(
        params,
        standard_max_points=search.get(
            "standard_max_points", DEFAULT_STANDARD_MAX_POINTS
        ),
        debug_dir=search.get("debug_dir"),
        timeout_seconds=search.get("timeout", 60),
        chrome_path=search.get("chrome_path", DEFAULT_CHROME_PATH),
        user_data_dir=search.get("cdp_user_data_dir", CDP_USER_DATA_DIR),
        debug_label=search_label,
        window_index=search_index,
    )
    result.target_dates = target_dates
    result.search_label = search_label
    return result


def save_results(results: list[HiltonSearchResult], output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    first = results[0]
    suffix = "search" if len(results) == 1 else "searches"
    output_file = os.path.join(
        output_dir,
        f"hilton_{first.hotel_code}_{first.arrival_date}_{len(results)}{suffix}.json",
    )
    with open(output_file, "w", encoding="utf-8") as file:
        json.dump([asdict(result) for result in results], file, indent=2)
    return output_file


async def main() -> None:
    if not RUN_CDP_SEARCHES:
        print("RUN_CDP_SEARCHES is disabled; no searches were run.")
        return

    print(f"Starting Chrome CDP Hilton search for {len(SEARCHES)} configured search(es).")
    results = await asyncio.gather(
        *(run_cdp_search(search, index) for index, search in enumerate(SEARCHES))
    )
    output_file = save_results(results, RESULTS_DIR)

    for search, result in zip(SEARCHES, results):
        print(
            f"\n{'#' * 72}\n"
            f"Hilton {search.get('hotel', DEFAULT_HOTEL)} | "
            f"Chrome CDP month anchored at {search['arrival']} | "
            f"{search.get('nights', 1)} night(s)\n"
            f"{'#' * 72}"
        )

        if result.error:
            print(f"\nError for {result.arrival_date}: {result.error}")
        if result.page_reference:
            print(f"Page reference: {result.page_reference}")
        if result.main_response_status:
            print(f"Main document status: {result.main_response_status}")
        if result.search_label:
            print(f"Search label: {result.search_label}")
        if result.akamai_challenge_detected and not result.rewards:
            print("Diagnostic: Akamai browser challenge detected.")
        if result.headless_chrome_detected:
            print("Diagnostic: rendered page contains HeadlessChrome client-hint data.")
        print(f"\nURL: {result.url}")
        print(f"Captured JSON responses: {result.raw_response_count}")
        result.print_table(
            standard_only=search.get("standard_only", False),
            target_dates=search.get("target_dates", []),
        )

        if search.get("debug_dir"):
            print(f"Saved CDP debug artifacts to {result.debug_prefix or search['debug_dir']}")

    print(f"\nSaved parsed results to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
