# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Viewport evidence capture backed by the maintained simulation preview."""

from __future__ import annotations

from typing import Any


def capture_graph_evidence(
    app,
    yaml_text: str,
    *,
    num_envs: int,
    num_steps: int,
    env_spacing: float,
) -> dict[str, Any]:
    """Capture a bounded preview and describe its event-to-frame mapping."""
    from isaaclab_arena.agentic_environment_generation.simapp.sim_preview import run_sim_preview

    result = run_sim_preview(
        app,
        yaml_text,
        num_envs=num_envs,
        num_steps=num_steps,
        env_spacing=env_spacing,
    )
    result.update({
        "capture": {
            "source": "viewport",
            "boundaries": [
                {"event": "preview_start", "control_step": 0, "video_frame_index": 0},
                {"event": "preview_end", "control_step": num_steps, "video_frame_index": num_steps},
            ],
            "camera_metadata": result.pop("camera_metadata"),
            "autoreset": False,
        }
    })
    return result
