#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Summarize Codex measurements and independent acceptance from the A/B pilot."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts" / "codex_collision_viz_ab"
RUNS = OUTPUT / "runs"


def parse_json_lines(path: Path) -> list[dict]:
    records = []
    if not path.exists():
        return records
    for line in path.read_text(errors="replace").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def usage_from_record(record: dict) -> dict | None:
    if record.get("type") == "token_usage_record":
        payload = record.get("payload", {})
        return payload.get("thread_token_usage") or payload.get("turn_token_usage") or payload.get("usage")
    if record.get("type") == "event_msg":
        payload = record.get("payload", {})
        if payload.get("type") == "token_count":
            return payload.get("info", {}).get("total_token_usage")
    if record.get("type") in {"turn.completed", "turn_completed"}:
        return record.get("usage")
    return None


def tool_name(record: dict) -> str | None:
    if record.get("type") == "response_item":
        payload = record.get("payload", {})
        if payload.get("type") in {"custom_tool_call", "function_call", "tool_call"}:
            return payload.get("name") or payload.get("tool_name")
    if record.get("type") == "item.completed":
        item = record.get("item", {})
        if item.get("type") in {"command_execution", "mcp_tool_call", "tool_call"}:
            return item.get("type")
    return None


def summarize_arm(arm: str) -> dict:
    run_dir = RUNS / arm
    records = parse_json_lines(run_dir / "codex.jsonl")
    usages = [usage for record in records if (usage := usage_from_record(record)) is not None]
    tools = Counter(name for record in records if (name := tool_name(record)) is not None)
    inference_calls = sum(
        record.get("type") == "item.completed" and record.get("item", {}).get("type") == "agent_message"
        for record in records
    )
    simulation_starts = sum("Simulation App Starting" in json.dumps(record) for record in records)
    run_record = json.loads((run_dir / "run_record.json").read_text())
    final = {}
    if (run_dir / "final.json").exists():
        try:
            final = json.loads((run_dir / "final.json").read_text())
        except json.JSONDecodeError:
            final = {"unparsed": (run_dir / "final.json").read_text(errors="replace")}
    images = [str(path.relative_to(OUTPUT)) for path in sorted((run_dir / "images").glob("*.png"))]
    acceptance = {}
    acceptance_path = run_dir / "acceptance" / "result.json"
    if acceptance_path.exists():
        acceptance = json.loads(acceptance_path.read_text())
    agent_completed = (
        run_record["return_code"] == 0
        and run_record["workspace_changes"]["allowed"]
        and final.get("outcome") == "success"
    )
    qualified = agent_completed and acceptance.get("episodes") == 5 and acceptance.get("successes", 0) >= 1
    return {
        "arm": arm,
        "agent_completed": agent_completed,
        "qualified": qualified,
        "wall_seconds": run_record["wall_seconds"],
        "codex_inference_calls": inference_calls,
        "token_usage": usages[-1] if usages else {},
        "tool_calls": dict(tools),
        "simulation_starts_observed": simulation_starts,
        "independent_acceptance": acceptance,
        "workspace_changes": run_record["workspace_changes"],
        "debug_images": images,
        "final": final,
    }


def main() -> None:
    summaries = [summarize_arm(arm) for arm in ("arm_amber", "arm_cobalt")]
    (OUTPUT / "summary.json").write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n")

    labels = {"arm_amber": "Control A", "arm_cobalt": "Treatment B"}
    by_arm = {summary["arm"]: summary for summary in summaries}
    control = by_arm["arm_amber"]
    treatment = by_arm["arm_cobalt"]
    time_reduction = 100 * (1 - treatment["wall_seconds"] / control["wall_seconds"])
    response_reduction = 100 * (1 - treatment["codex_inference_calls"] / control["codex_inference_calls"])
    lines = [
        "# Codex Collision-Visualization A/B Pilot",
        "",
        "One run per arm; results are directional and not statistically significant.",
        "The timed Codex sessions did not run OpenPI. Policy acceptance ran afterward.",
        "",
        "## Directional comparison",
        (
            f"- Treatment finished {time_reduction:.1f}% faster and used "
            f"{response_reduction:.1f}% fewer Codex model responses."
        ),
        (
            "- Independent OpenPI acceptance: "
            f"control {control['independent_acceptance'].get('successes', 0)}/"
            f"{control['independent_acceptance'].get('episodes', 0)}; "
            f"treatment {treatment['independent_acceptance'].get('successes', 0)}/"
            f"{treatment['independent_acceptance'].get('episodes', 0)}."
        ),
        "",
    ]
    for summary in summaries:
        lines.extend([
            f"## {labels[summary['arm']]}",
            f"- Agent completed: {summary['agent_completed']}",
            f"- Qualified after external acceptance: {summary['qualified']}",
            f"- Timed Codex wall time: {summary['wall_seconds']:.1f} s",
            f"- Codex inference calls: {summary['codex_inference_calls']}",
            f"- Token usage: `{json.dumps(summary['token_usage'], sort_keys=True)}`",
            f"- Tool calls: `{json.dumps(summary['tool_calls'], sort_keys=True)}`",
            f"- Observed SimulationApp starts: {summary['simulation_starts_observed']}",
            (
                "- Independent OpenPI acceptance: "
                f"{summary['independent_acceptance'].get('successes', 0)}/"
                f"{summary['independent_acceptance'].get('episodes', 0)}"
            ),
            f"- Agent validation attempts: {len(summary['final'].get('validation_runs', []))}",
            f"- Final relation diff: `{json.dumps(summary['final'].get('relation_changes', []))}`",
            f"- Workspace changes allowed: {summary['workspace_changes']['allowed']}",
            f"- Raw log: [{summary['arm']} Codex JSONL](runs/{summary['arm']}/codex.jsonl)",
            f"- Independent acceptance log: [run.log](runs/{summary['arm']}/acceptance/run.log)",
        ])
        for image in summary["debug_images"]:
            lines.append(f"- Debug image: ![debug image]({image})")
        lines.append("")
    (OUTPUT / "report.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
