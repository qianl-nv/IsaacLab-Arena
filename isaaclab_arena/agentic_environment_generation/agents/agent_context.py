# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for env-generation sub-agents."""

from __future__ import annotations

from isaaclab_arena.agentic_environment_generation.agents.prompt_normalization_agent import NormalizedPrompt


def matched_assets_block(normalized: NormalizedPrompt) -> str:
    """Format registry-matched asset context for tasks/relations agent user prompts."""
    background_id = normalized.background.name
    node_ids = [obj.name for obj in normalized.objects] + [background_id]
    lines = [
        "MATCHED ASSETS (registry keys resolved from AssetSpec.query; use node ids below in output):",
        (
            f"- robot: node id={normalized.robot.name!r}, "
            f"registry={normalized.robot.registry_name!r}, query={normalized.robot.query!r}"
        ),
        (
            f"- background: node id={background_id!r}, "
            f"registry={normalized.background.registry_name!r}, query={normalized.background.query!r}"
        ),
    ]
    for obj in normalized.objects:
        lines.append(
            f"- object: node id={obj.name!r}, registry={obj.registry_name!r}, "
            f"query={obj.query!r}, description={obj.description!r}"
        )
    lines.append(f"NODE IDS (use in task params and relation subject/reference): {', '.join(node_ids)}")
    return "\n".join(lines)
