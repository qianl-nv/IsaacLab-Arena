# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Shared graph-environment construction and zero-action execution."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import gymnasium as gym

    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg


def env_builder_from_graph_spec(
    graph_spec: ArenaEnvGraphSpec,
    builder_cfg: ArenaEnvBuilderCfg,
    *,
    env_name: str | None = None,
) -> ArenaEnvBuilder:
    """Create an Arena builder from a validated graph spec."""
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder

    arena_env = graph_spec.to_arena_env()
    if env_name is not None:
        arena_env.name = env_name
    return ArenaEnvBuilder(arena_env, builder_cfg)


def make_env_from_graph_spec(
    graph_spec: ArenaEnvGraphSpec,
    builder_cfg: ArenaEnvBuilderCfg,
    *,
    env_name: str | None = None,
    render_mode: str | None = None,
) -> gym.Env:
    """Build and register an environment from a validated graph spec."""
    builder = env_builder_from_graph_spec(graph_spec, builder_cfg, env_name=env_name)
    return builder.make_registered(render_mode=render_mode)


def run_zero_action_steps(
    env: gym.Env,
    num_steps: int,
    *,
    inference_mode: bool = True,
    reset_policy: bool = True,
    handle_episode_ends: bool = True,
    on_episode_done: Callable[[int, list[int]], None] | None = None,
) -> None:
    """Reset an environment and execute a zero-action policy for a bounded step count."""
    import torch

    from isaaclab_arena.policy.zero_action_policy import ZeroActionPolicy, ZeroActionPolicyCfg

    assert num_steps >= 0, f"num_steps must be non-negative, got {num_steps}"
    policy = ZeroActionPolicy(ZeroActionPolicyCfg())
    obs, _ = env.reset()
    if reset_policy:
        policy.reset()
    for step in range(num_steps):
        inference_context = torch.inference_mode() if inference_mode else nullcontext()
        with inference_context:
            action = policy.get_action(env, obs)
            obs, _, terminated, truncated, _ = env.step(action)
        if handle_episode_ends and (terminated | truncated).any():
            env_ids = (terminated | truncated).nonzero().flatten()
            policy.reset(env_ids=env_ids)
            if on_episode_done is not None:
                on_episode_done(step, env_ids.tolist())
