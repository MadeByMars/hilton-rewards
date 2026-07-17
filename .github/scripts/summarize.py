#!/usr/bin/env python3
"""Summarize Hilton award search results for GitHub Actions."""

import glob
import json
import os
from io import StringIO
from typing import Any

RESULTS_DIR = os.environ.get("RESULTS_DIR", "results")


def reward_points(reward: dict[str, Any]) -> int:
    points = reward.get("points")
    return int(points) if points is not None else 10**12


def display_points(reward: dict[str, Any]) -> str:
    points = reward.get("points")
    return f"{points:,}" if points is not None else "-"


def main() -> None:
    output_file = os.environ.get("GITHUB_OUTPUT")
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    observed_standard_count = 0
    standalone_standard_count = 0
    grouped_alerts: dict[str, dict[str, Any]] = {}
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
            alert_group = result.get("alert_group")
            alert_required_dates = result.get("alert_required_dates") or []
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
            observed_standard_count += len(standards)

            if alert_group:
                group = grouped_alerts.setdefault(
                    alert_group,
                    {
                        "hotel": hotel,
                        "required_dates": set(),
                        "standard_by_date": {},
                        "labels": [],
                    },
                )
                group["required_dates"].update(alert_required_dates or target_dates)
                group["labels"].append(label)
                for reward in standards:
                    reward_date = reward.get("date")
                    if not reward_date:
                        continue
                    current = group["standard_by_date"].get(reward_date)
                    if current is None or reward_points(reward) < reward_points(current):
                        group["standard_by_date"][reward_date] = reward
            else:
                standalone_standard_count += len(standards)

            log(f"\n{'#' * 72}")
            log(f"  {hotel} | {arrival} | {nights} night(s)")
            log(f"  Label: {label}")
            if alert_group:
                log(f"  Alert group: {alert_group}")
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

    complete_group_count = 0
    complete_group_standard_count = 0
    if grouped_alerts:
        log(f"\n{'=' * 72}")
        log("  ALERT GROUPS")
        log(f"{'=' * 72}")

    for group_name, group in sorted(grouped_alerts.items()):
        required_dates = sorted(group["required_dates"])
        standard_by_date = group["standard_by_date"]
        missing_dates = [
            reward_date
            for reward_date in required_dates
            if reward_date not in standard_by_date
        ]
        is_complete = bool(required_dates) and not missing_dates
        if is_complete:
            complete_group_count += 1
            complete_group_standard_count += len(required_dates)

        log(f"\nAlert group: {group_name}")
        log(f"Hotel: {group['hotel']}")
        log(f"Required dates: {', '.join(required_dates) if required_dates else '-'}")
        log(f"Complete group: {'YES' if is_complete else 'NO'}")
        for reward_date in required_dates:
            reward = standard_by_date.get(reward_date)
            if reward:
                log(
                    f"  OK {reward_date}: {display_points(reward)} points "
                    f"({reward.get('reward_type') or 'Unknown'})"
                )
            else:
                log(f"  MISSING {reward_date}: no standard reward")

    alert_standard_count = standalone_standard_count + complete_group_standard_count

    log(f"\n{'=' * 72}")
    log(f"  OBSERVED STANDARD ROOM REWARDS: {observed_standard_count}")
    log(f"  STANDALONE ALERT STANDARD REWARDS: {standalone_standard_count}")
    log(f"  COMPLETE ALERT GROUPS: {complete_group_count}")
    log(f"  ALERT-ELIGIBLE STANDARD REWARDS: {alert_standard_count}")
    log(f"{'=' * 72}")

    content = output.getvalue()
    if output_file:
        with open(output_file, "a", encoding="utf-8") as file:
            file.write(f"standard_count={alert_standard_count}\n")
            file.write(f"observed_standard_count={observed_standard_count}\n")
            file.write(f"complete_alert_group_count={complete_group_count}\n")
            file.write(
                f"has_standard_rewards={'true' if alert_standard_count > 0 else 'false'}\n"
            )
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
