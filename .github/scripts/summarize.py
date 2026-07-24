#!/usr/bin/env python3
"""Summarize Hilton award search results for GitHub Actions."""

import glob
import json
import os
from datetime import datetime, timedelta
from io import StringIO
from typing import Any

RESULTS_DIR = os.environ.get("RESULTS_DIR", "results")


def reward_points(reward: dict[str, Any]) -> int:
    points = reward.get("points")
    return int(points) if points is not None else 10**12


def display_points(reward: dict[str, Any]) -> str:
    points = reward.get("points")
    return f"{points:,}" if points is not None else "-"


def add_days(date_text: str, days: int) -> str:
    parsed = datetime.strptime(date_text, "%Y-%m-%d").date()
    return (parsed + timedelta(days=days)).isoformat()


def date_range(start_date: str, end_date: str) -> list[str]:
    current = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    dates: list[str] = []
    while current < end:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def segment_points(segment: dict[str, Any]) -> int:
    return reward_points(segment["reward"])


def find_covering_combinations(
    segments: list[dict[str, Any]],
    stay_start: str,
    stay_end: str,
    limit: int = 20,
) -> list[list[dict[str, Any]]]:
    by_start: dict[str, list[dict[str, Any]]] = {}
    for segment in segments:
        if segment["start"] < stay_start or segment["end"] > stay_end:
            continue
        by_start.setdefault(segment["start"], []).append(segment)

    for candidates in by_start.values():
        candidates.sort(key=lambda item: (item["end"], segment_points(item)))

    combinations: list[list[dict[str, Any]]] = []

    def walk(current: str, path: list[dict[str, Any]]) -> None:
        if len(combinations) >= limit:
            return
        if current == stay_end:
            combinations.append(path.copy())
            return
        for segment in by_start.get(current, []):
            if segment["end"] <= current:
                continue
            path.append(segment)
            walk(segment["end"], path)
            path.pop()

    walk(stay_start, [])
    return combinations


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
            nights = result.get("nights") or 1
            nights_count = int(nights)
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
                        "alert_start": result.get("alert_start"),
                        "alert_end": result.get("alert_end"),
                        "required_dates": set(),
                        "segments": [],
                        "labels": [],
                    },
                )
                group["alert_start"] = group["alert_start"] or result.get("alert_start")
                group["alert_end"] = group["alert_end"] or result.get("alert_end")
                group["required_dates"].update(alert_required_dates or target_dates)
                group["labels"].append(label)
                for reward in standards:
                    reward_date = reward.get("date")
                    if not reward_date:
                        continue
                    group["segments"].append(
                        {
                            "start": reward_date,
                            "end": add_days(reward_date, nights_count),
                            "nights": nights_count,
                            "reward": reward,
                            "label": label,
                        }
                    )
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
                reward_date = reward.get("date")
                stay_end = add_days(reward_date, nights_count) if reward_date else "?"
                stay_text = (
                    reward_date
                    if nights_count == 1
                    else f"{reward_date} to {stay_end} ({nights_count} nights)"
                )
                log(
                    "  STANDARD "
                    f"{stay_text}: {display_points(reward)} points "
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
        stay_start = group.get("alert_start")
        stay_end = group.get("alert_end")
        required_dates = sorted(group["required_dates"])
        if (not stay_start or not stay_end) and required_dates:
            stay_start = required_dates[0]
            stay_end = add_days(required_dates[-1], 1)

        segments = sorted(
            group["segments"],
            key=lambda item: (item["start"], item["end"], segment_points(item)),
        )
        combinations = (
            find_covering_combinations(segments, stay_start, stay_end)
            if stay_start and stay_end
            else []
        )
        covered_dates = set()
        for segment in segments:
            if not stay_start or not stay_end:
                continue
            for reward_date in date_range(segment["start"], segment["end"]):
                if stay_start <= reward_date < stay_end:
                    covered_dates.add(reward_date)
        missing_dates = [
            reward_date
            for reward_date in required_dates
            if reward_date not in covered_dates
        ]
        is_complete = bool(combinations)
        if is_complete:
            complete_group_count += 1
            complete_group_standard_count += len(required_dates)

        log(f"\nAlert group: {group_name}")
        log(f"Hotel: {group['hotel']}")
        if stay_start and stay_end:
            log(f"Stay window: {stay_start} to {stay_end}")
        log(f"Required dates: {', '.join(required_dates) if required_dates else '-'}")
        log(f"Complete group: {'YES' if is_complete else 'NO'}")
        log(f"Standard stay segments: {len(segments)}")
        for segment in segments:
            reward = segment["reward"]
            log(
                f"  {segment['start']} to {segment['end']} "
                f"({segment['nights']} night(s)): {display_points(reward)} points "
                f"({reward.get('reward_type') or 'Unknown'})"
            )

        if combinations:
            log(f"Covering combinations: {len(combinations)}")
            for index, combination in enumerate(combinations[:10], start=1):
                pieces = [
                    f"{segment['start']} to {segment['end']} ({segment['nights']}n)"
                    for segment in combination
                ]
                log(f"  {index}. {' + '.join(pieces)}")
            if len(combinations) > 10:
                log(f"  ... {len(combinations) - 10} more combination(s)")
        else:
            if missing_dates:
                log(
                    "Uncovered dates by any standard segment: "
                    f"{', '.join(missing_dates)}"
                )
            else:
                log("No exact non-overlapping combination covers the full stay.")

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
