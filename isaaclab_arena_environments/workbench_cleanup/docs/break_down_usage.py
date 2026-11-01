# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Attribute the frozen workbench usage snapshot to retrospectively reviewed substeps."""

import json
from bisect import bisect_right
from collections import Counter
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
CATEGORIES = {
    "environment_yaml": {
        "label": "Generate and fix environment YAML",
        "scope": "Asset inspection, task schema, scene placement, toolbox reset, and collider configuration.",
        "tool_ranges": "1-17,19-24,26,30-31,35-37,39-52,54-60,62,78,80,89,95-98,112",
    },
    "force_demo": {
        "label": "Generate force demo and validator",
        "scope": "Author the JSONL recipe and validator, correct controller orientation, and add scene assertions.",
        "tool_ranges": "25,27,61,64",
    },
    "experiment_config": {
        "label": "Generate and fix experiment configuration",
        "scope": "Experiment authoring, documentation lookup, rollout-limit changes, and the short-timeout wrapper.",
        "tool_ranges": "29,65-66,106-108,120-131",
    },
    "tests_and_validation": {
        "label": "Run and pass tests / physical validation",
        "scope": (
            "Pytest, lint, demo and semantic checks, simulation retries, recording, and evaluation smoke execution."
        ),
        "tool_ranges": "18,28,63,67-77,79,81-85,87-88,90-94,100-103,105,110-111,113-119,132-136",
    },
    "reporting_overhead": {
        "label": "README, accounting, and context overhead",
        "scope": "README and telemetry work, including the context compaction recorded during reporting.",
        "tool_ranges": "32-34,38,53,86,99,104,109,137",
    },
}


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main():
    original = json.loads((BASE / "work_log.json").read_text())
    assert original["measurement_cutoff"] == "2026-10-31T18:45:53.178762+00:00"
    owners = {}
    for category, definition in CATEGORIES.items():
        for span in definition["tool_ranges"].split(","):
            bounds = [int(value) for value in span.split("-")]
            for index in range(bounds[0], bounds[-1] + 1):
                assert index not in owners, f"Duplicate attribution: {index}"
                owners[index] = category
    assert set(owners) == set(range(1, len(original["tool_log"]) + 1))
    tool_times = [timestamp(row["timestamp"]) for row in original["tool_log"]]
    totals = {key: {"wall_microseconds": 0, "inference_calls": 0, "tokens": Counter()} for key in CATEGORIES}
    intervals = []
    previous = timestamp(original["started_at"])
    for index, row in enumerate(original["inference_log"], 1):
        end = timestamp(row["timestamp"])
        tool_index = bisect_right(tool_times, end)
        category = owners[tool_index]
        elapsed_us = round((end - previous).total_seconds() * 1_000_000)
        assert elapsed_us >= 0
        usage = {key: value for key, value in row.items() if key != "timestamp"}
        totals[category]["tokens"].update(usage)
        totals[category]["inference_calls"] += 1
        totals[category]["wall_microseconds"] += elapsed_us
        intervals.append({
            "inference_index": index,
            "preceding_tool_index": tool_index,
            "category": category,
            "start": previous.isoformat(),
            "end": end.isoformat(),
            "wall_microseconds": elapsed_us,
            "tokens": usage,
        })
        previous = end
    tail_us = round((timestamp(original["measurement_cutoff"]) - previous).total_seconds() * 1_000_000)
    assert tail_us >= 0
    totals["reporting_overhead"]["wall_microseconds"] += tail_us
    wall_us = sum(row["wall_microseconds"] for row in totals.values())
    assert round(wall_us / 1_000_000, 3) == original["wall_time_seconds"]
    assert sum(row["inference_calls"] for row in totals.values()) == original["inference_calls"]
    combined_tokens = Counter()
    for row in totals.values():
        combined_tokens.update(row["tokens"])
    assert dict(combined_tokens) == original["tokens"]
    result = {
        "source": "work_log.json",
        "started_at": original["started_at"],
        "measurement_cutoff": original["measurement_cutoff"],
        "method": [
            "Retrospective estimates by dominant action, manually reviewed against the original tool-call timeline.",
            "Tool ordinals refer to work_log.json tool_log (one-based); batches with multiple purposes have one owner.",
            (
                "Each recorded inference is assigned to its immediately preceding tool call; one compaction shares"
                " reporting tool 104."
            ),
            (
                "Elapsed time from the previous inference timestamp to the current one is charged to the current"
                " inference category."
            ),
            (
                "These non-overlapping wall-time allocations include waiting and reasoning; they are not isolated"
                " process runtimes."
            ),
            "Background tests and rendering overlap other work. No parallel runtime is added twice.",
            (
                "Original counts/tokens are exact; category attribution is approximate. This follow-up analysis is"
                " excluded."
            ),
            "Cached input is included in input tokens; reasoning output is included in output tokens.",
        ],
        "categories": {key: {**CATEGORIES[key], **value} for key, value in totals.items()},
        "totals": {
            "wall_microseconds": wall_us,
            "inference_calls": original["inference_calls"],
            "tokens": original["tokens"],
        },
        "unmodeled_tail_microseconds_assigned_to_reporting": tail_us,
        "inference_intervals": intervals,
    }
    (BASE / "work_breakdown.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Substep | wall seconds | calls | input | cached input | output | total")
    for key, row in totals.items():
        tokens = row["tokens"]
        print(
            f"{key} | {row['wall_microseconds'] / 1_000_000:.3f} | {row['inference_calls']}"
            f" | {tokens['input_tokens']} | {tokens['cached_input_tokens']}"
            f" | {tokens['output_tokens']} | {tokens['total_tokens']}"
        )


if __name__ == "__main__":
    main()
