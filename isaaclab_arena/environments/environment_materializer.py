# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Materialize Arena authoring descriptions into Isaac Lab environment configs."""

from __future__ import annotations

from copy import deepcopy

from isaaclab.scene import InteractiveSceneCfg
from isaaclab.utils.configclass import configclass

from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
from isaaclab_arena.environments.isaaclab_arena_manager_based_env_cfg import IsaacLabArenaManagerBasedRLEnvCfg


@configclass
class ArenaEnvironmentSourceCfg(IsaacLabArenaManagerBasedRLEnvCfg):
    """Unmaterialized Arena source accepted by Isaac Lab's task config pipeline."""

    arena_environment: IsaacLabArenaEnvironment | None = None
    """Arena authoring description to compile."""

    arena_builder: ArenaEnvBuilderCfg | None = None
    """Arena compilation settings."""

    variation_overrides: list[str] | None = None
    """Hydra-style variation overrides consumed by the Arena compiler."""


def make_arena_environment_source_cfg(
    arena_environment: IsaacLabArenaEnvironment,
    builder_cfg: ArenaEnvBuilderCfg,
    variation_overrides: list[str] | None = None,
) -> ArenaEnvironmentSourceCfg:
    """Create an unmaterialized config for Gym registration."""
    cfg = ArenaEnvironmentSourceCfg(
        scene=InteractiveSceneCfg(
            num_envs=builder_cfg.num_envs,
            env_spacing=builder_cfg.env_spacing,
            replicate_physics=False,
        ),
    )
    # Configclass initialization deep-copies object-valued fields. Keep the
    # caller's authoring graph here so direct composition retains its existing
    # in-place variation semantics; the Gym entry-point factory deep-copies the
    # complete source before registered materialization.
    cfg.arena_environment = arena_environment
    cfg.arena_builder = deepcopy(builder_cfg)
    cfg.variation_overrides = deepcopy(variation_overrides)
    cfg.seed = builder_cfg.seed
    cfg.sim.device = builder_cfg.device
    cfg.sim.use_fabric = not builder_cfg.disable_fabric
    return cfg


def materialize_arena_environment_cfg(source_cfg: ArenaEnvironmentSourceCfg) -> IsaacLabArenaManagerBasedRLEnvCfg:
    """Compile an Arena source after Isaac Lab has applied configuration overrides."""
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder

    assert source_cfg.arena_environment is not None, "Arena environment source is not configured."
    assert source_cfg.arena_builder is not None, "Arena builder source is not configured."
    builder_cfg = deepcopy(source_cfg.arena_builder)
    builder_cfg.num_envs = source_cfg.scene.num_envs
    builder_cfg.env_spacing = source_cfg.scene.env_spacing
    builder_cfg.seed = source_cfg.seed
    builder_cfg.device = source_cfg.sim.device
    builder_cfg.disable_fabric = not source_cfg.sim.use_fabric

    builder = ArenaEnvBuilder(
        source_cfg.arena_environment,
        builder_cfg,
        hydra_overrides=source_cfg.variation_overrides,
    )
    env_cfg, env_kwargs = builder._compose_manager_cfg()
    env_cfg._variation_recorder = env_kwargs["variation_recorder"]
    env_cfg._variation_replay_scheduler = env_kwargs["variation_replay_scheduler"]
    return env_cfg
