# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Scene preflight and settled-placement checks for the SimApp sidecar."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def check_graph_scene(
    app,
    yaml_text: str,
    *,
    output_path: str,
    mode: str,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    """Run one sampled, existing-pool, or static scene check."""
    import yaml

    from isaaclab_arena.agentic_environment_generation.simapp.report import validated_output_dir
    from isaaclab_arena.agentic_environment_generation.simapp.sim_preview import _close_env_and_reset_sim
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    raw = yaml.safe_load(yaml_text)
    assert isinstance(raw, dict), f"expected graph-spec mapping, got {type(raw).__name__}"
    graph_spec = ArenaEnvGraphSpec.model_validate(raw)
    output_dir = validated_output_dir(output_path)
    _close_env_and_reset_sim(suppress_exceptions=True, app=app)
    if mode == "sampled":
        result = _sample_settled_layouts(graph_spec, output_dir, configuration)
        _close_env_and_reset_sim(suppress_exceptions=True, app=app)
        return result
    return _check_pool_or_static(app, graph_spec, output_dir, mode, configuration)


def _sample_settled_layouts(graph_spec, output_dir: Path, configuration: dict[str, Any]) -> dict[str, Any]:
    from isaaclab_arena.offline_placement.recording import record_settled_placement_layouts
    from isaaclab_arena.offline_placement.recording_config import PlacementRecordingCfg
    from isaaclab_arena.offline_placement.settled_placement_params import SettledPlacementParams

    placements_path = output_dir / "accepted_layouts.jsonl"
    settle = SettledPlacementParams(
        num_steps=int(configuration.get("settle_steps", 120)),
        validators=configuration.get("validators") or SettledPlacementParams().validators,
    )
    cfg = PlacementRecordingCfg(
        env_spec="",
        output=str(placements_path),
        num_envs=int(configuration.get("num_envs", 1)),
        env_spacing=float(configuration.get("env_spacing", 30.0)),
        layouts_per_env=int(configuration.get("layouts_per_env", 3)),
        min_layouts=int(configuration.get("min_layouts", 1)),
        max_batches=int(configuration.get("max_batches", 5)),
        seed=int(configuration.get("seed", 42)),
        presets=configuration.get("presets"),
        render=bool(configuration.get("render", False)),
        settle=settle,
    )
    summary = record_settled_placement_layouts(
        cfg,
        device=str(configuration.get("device", "cpu")),
        arena_env=graph_spec.to_arena_env(),
    )
    return {
        "mode": "sampled",
        "status": "completed" if summary.accepted >= cfg.min_layouts else "incomplete",
        "accepted": summary.accepted,
        "attempted": summary.attempted,
        "requested": cfg.min_layouts,
        "rejections": {f"{env_id}:{batch}": reason for (env_id, batch), reason in summary.rejections.items()},
        "placements_path": str(summary.output) if summary.output is not None else None,
    }


def _check_pool_or_static(app, graph_spec, output_dir: Path, mode: str, configuration: dict[str, Any]):
    import torch

    from isaaclab_arena.agentic_environment_generation.simapp.environment_runtime import env_builder_from_graph_spec
    from isaaclab_arena.agentic_environment_generation.simapp.sim_preview import _close_env_and_reset_sim
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
    from isaaclab_arena.offline_placement.pool_validation import validate_pool_layouts
    from isaaclab_arena.policy.zero_action_policy import ZeroActionPolicy, ZeroActionPolicyCfg
    from isaaclab_arena.relations.physics_settle_params import PhysicsSettleParams

    num_envs = int(configuration.get("num_envs", 1))
    builder_cfg = ArenaEnvBuilderCfg(
        num_envs=num_envs,
        env_spacing=float(configuration.get("env_spacing", 30.0)),
        seed=int(configuration.get("seed", 42)),
        device=str(configuration.get("device", "cpu")),
        presets=configuration.get("presets"),
        resolve_on_reset=False,
    )
    env = None
    try:
        env = env_builder_from_graph_spec(graph_spec, builder_cfg).make_registered()
        obs, _ = env.reset()
        settle_steps = int(configuration.get("settle_steps", 120))
        if mode == "pool":
            results = validate_pool_layouts(
                env,
                settle_params=PhysicsSettleParams(
                    num_steps=settle_steps,
                    lin_vel_thresh=float(configuration.get("linear_speed_m_per_s", 0.015)),
                    ang_vel_thresh=float(configuration.get("angular_speed_rad_per_s", 0.1)),
                ),
                render=bool(configuration.get("render", False)),
            )
            if results is None:
                return {
                    "mode": "pool",
                    "status": "unsupported",
                    "reason": "scene has no pooled placement candidates",
                    "output_path": str(output_dir),
                }
            layouts = [
                {
                    "env_id": env_id,
                    "layout_index": layout_index,
                    "checks": dict(checks.validation_results),
                    "required_checks": sorted(checks.required_checks or checks.validation_results),
                    "passed": checks.do_all_required_validation_checks_pass(),
                }
                for env_id, layout_index, checks in results
            ]
            return {"mode": "pool", "status": "completed", "layouts": layouts, "output_path": str(output_dir)}

        policy = ZeroActionPolicy(ZeroActionPolicyCfg())
        for _ in range(settle_steps):
            with torch.inference_mode():
                actions = policy.get_action(env, obs)
                obs, _, _, _, _ = env.step(actions)
        return {
            "mode": "static",
            "status": "completed",
            "sampling": "inapplicable",
            "settle_steps": settle_steps,
            "output_path": str(output_dir),
        }
    finally:
        _close_env_and_reset_sim(env, app=app, suppress_exceptions=True)
