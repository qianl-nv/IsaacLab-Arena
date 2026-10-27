# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded spawned-scene probes for authoring diagnostics."""

from __future__ import annotations

from typing import Any


def probe_graph_object(
    app,
    yaml_text: str,
    *,
    object_name: str,
    num_steps: int,
    env_spacing: float,
) -> dict[str, Any]:
    """Measure one object's passive displacement and available contact sensors."""
    import torch
    import yaml

    from isaaclab_arena.agentic_environment_generation.simapp.environment_runtime import env_builder_from_graph_spec
    from isaaclab_arena.agentic_environment_generation.simapp.sim_preview import _close_env_and_reset_sim, _preview_cfg
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.policy.zero_action_policy import ZeroActionPolicy, ZeroActionPolicyCfg

    raw = yaml.safe_load(yaml_text)
    assert isinstance(raw, dict), f"expected graph-spec mapping, got {type(raw).__name__}"
    graph_spec = ArenaEnvGraphSpec.model_validate(raw)
    builder_cfg = _preview_cfg(num_envs=1, env_spacing=env_spacing)
    builder = env_builder_from_graph_spec(graph_spec, builder_cfg)
    env = None
    _close_env_and_reset_sim(suppress_exceptions=True, app=app)
    try:
        env = builder.make_registered()
        obs, _ = env.reset()
        sim_env = env.unwrapped
        scene_object = sim_env.scene.rigid_objects.get(object_name)
        if scene_object is None:
            scene_object = sim_env.scene.articulations.get(object_name)
        assert scene_object is not None, f"scene has no rigid object or articulation named {object_name!r}"
        start_pose = scene_object.data.root_pose_w[0].detach().cpu().clone()
        policy = ZeroActionPolicy(ZeroActionPolicyCfg())
        for _ in range(num_steps):
            with torch.inference_mode():
                actions = policy.get_action(env, obs)
                obs, _, _, _, _ = env.step(actions)
        end_pose = scene_object.data.root_pose_w[0].detach().cpu().clone()
        displacement = torch.linalg.vector_norm(end_pose[:3] - start_pose[:3]).item()
        contacts = _contact_sensor_measurements(sim_env.scene.sensors)
        return {
            "object_name": object_name,
            "num_steps": num_steps,
            "start_pose_w": start_pose.tolist(),
            "end_pose_w": end_pose.tolist(),
            "displacement_m": displacement,
            "contact_sensors": contacts,
            "wrench_trace": {
                "status": "unsupported",
                "reason": "passive probe applies no external wrench; use a T2 force recipe",
            },
        }
    finally:
        _close_env_and_reset_sim(env, app=app, suppress_exceptions=True)


def _contact_sensor_measurements(sensors: dict[str, object]) -> dict[str, Any]:
    import torch

    measurements = {}
    for name, sensor in sensors.items():
        net_forces_w = getattr(getattr(sensor, "data", None), "net_forces_w", None)
        if net_forces_w is None:
            continue
        forces = net_forces_w.detach()
        measurements[name] = {
            "max_force_n": float(torch.linalg.vector_norm(forces, dim=-1).max().cpu()),
            "shape": list(forces.shape),
        }
    return measurements
