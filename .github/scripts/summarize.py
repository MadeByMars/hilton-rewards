#!/usr/bin/env python3
"""Summarize Hilton award search results for GitHub Actions."""

import glob
import json
import os
from io import StringIO
from typing import Any

RESULTS_DIR = "results"


def reward_points(reward: dict[str, Any]) -> int:
    points = reward.get("points")
    return int(points) if points is not None else 10**12


def display_points(reward: dict[str, Any]) -> str:
    points = reward.get("points")
    return f"{points:,}" if points is not None else "-"


def main() -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    total_standard = 0
    output = StringIO()

    def log(message: str = "") -> None:
        print(message)
        output.write(message + "\n")

    log("=== Hilton Reward Search Results ===")

    result_files = sorted(glob.glob(f"{RESULTS_DIR}/hilton_*.json"))
    if not result_files:
        log("No Hilton result files found.")

    for filepath in result_files:
        with open(filepath, encoding="utf-8") as file:
            searches = json.load(file)

        for result in searches:
            label = result.get("search_label") or "search"
            hotel = result.get("hotel_code", "?")
            arrival = result.get("arrival_date", "?")
            nights = result.get("nights", "?")
            target_dates = result.get("target_dates") or []
            rewards = result.get("rewards") or []
            scoped_rewards = [
                reward
                for reward in rewards
                if not target_dates or reward.get("date") in target_dates
            ]
            available = [reward for reward in scoped_rewards if reward.get("available")]
            standards = [
                reward
                for reward in available
                if reward.get("standard")
            ]
            total_standard += len(standards)

            log(f"\n{'#' * 72}")
            log(f"  {hotel} | {arrival} | {nights} night(s)")
            log(f"  Label: {label}")
            if target_dates:
                log(f"  Target dates: {', '.join(target_dates)}")
            if result.get("error"):
                log(f"  Error: {result['error']}")
            log(f"{'#' * 72}")
            log(f"  Parsed reward nights: {len(scoped_rewards)}")
            log(f"  Available reward nights: {len(available)}")
            log(f"  Standard room rewards: {len(standards)}")

            for reward in sorted(standards, key=lambda item: (item.get("date"), reward_points(item))):
                log(
                    "  STANDARD "
                    f"{reward.get('date')}: {display_points(reward)} points "
                    f"({reward.get('reward_type') or 'Unknown'})"
                )

            if available:
                best = min(available, key=reward_points)
                log(
                    "  Lowest available reward: "
                    f"{display_points(best)} points "
                    f"({best.get('reward_type') or 'Unknown'}) on {best.get('date')}"
                )

    log(f"\n{'=' * 72}")
    log(f"  TOTAL STANDARD ROOM REWARDS: {total_standard}")
    log(f"{'=' * 72}")

    content = output.getvalue()
    if output_file:
        with open(output_file, "a", encoding="utf-8") as file:
            file.write(f"standard_count={total_standard}\n")
            file.write(f"has_standard_rewards={'true' if total_standard > 0 else 'false'}\n")
            file.write("CONTENT<<EOF\n")
            file.write(content)
            file.write("EOF\n")

    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as file:
            file.write("## Hilton Reward Search Results\n\n")
            file.write("```text\n")
            file.write(content)
            file.write("```\n")


if __name__ == "__main__":
    main()
