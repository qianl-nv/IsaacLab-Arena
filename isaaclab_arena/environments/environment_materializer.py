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

    @property
    def arena_environment(self) -> IsaacLabArenaEnvironment | None:
        """Live authoring graph, excluded from configclass/Hydra serialization."""
        return getattr(self, "__arena_environment__", None)

    @arena_environment.setter
    def arena_environment(self, value: IsaacLabArenaEnvironment) -> None:
        # configclass skips dunder attributes in to_dict(), while deepcopy still
        # copies them (including cycles) for each registered source factory call.
        self.__arena_environment__ = value

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
    cfg.__arena_defaults__ = cfg.to_dict()
    return cfg


def _copy_source_overrides(source_cfg, env_cfg) -> None:
    """Copy changed source fields without replacing defaults authored by the compiler."""
    source_dict = source_cfg.to_dict()
    explicit_paths = getattr(source_cfg, "__isaaclab_explicit_overrides__", ())

    def copy_fields(source, baseline, target, current, prefix=""):
        for name, value in current.items():
            if not prefix and name in {
                "arena_builder",
                "arena_materialization",
                "arena_source",
                "variation_overrides",
            }:
                continue
            path = f"{prefix}.{name}" if prefix else name
            previous = baseline.get(name)
            explicitly_overridden = any(item == path or item.startswith(f"{path}.") for item in explicit_paths)
            if name in baseline and value == previous and not explicitly_overridden:
                continue
            source_value = source[name] if isinstance(source, dict) else getattr(source, name)
            changed = path in explicit_paths or name not in baseline or type(value) is not type(previous)
            if not changed and isinstance(value, dict):
                target_value = target[name] if isinstance(target, dict) else getattr(target, name)
                copy_fields(source_value, previous, target_value, value, path)
                continue
            if not changed:
                changed = value != previous
            if changed:
                if isinstance(target, dict):
                    target[name] = deepcopy(source_value)
                else:
                    setattr(target, name, deepcopy(source_value))

    copy_fields(source_cfg, source_cfg.__arena_defaults__, env_cfg, source_dict)
    # These builder settings apply even when they equal the initial source.
    env_cfg.sim.device = source_cfg.sim.device
    env_cfg.sim.use_fabric = source_cfg.sim.use_fabric


def materialize_arena_environment_cfg(source_cfg: ArenaEnvironmentSourceCfg) -> IsaacLabArenaManagerBasedRLEnvCfg:
    """Compile an Arena source after Isaac Lab has applied configuration overrides."""
    from isaaclab_arena.environments.arena_env_compiler import (
        compile_arena_manager_cfg,
        configure_arena_visualizer_defaults,
    )

    assert source_cfg.arena_environment is not None, "Arena environment source is not configured."
    assert source_cfg.arena_builder is not None, "Arena builder source is not configured."
    builder_cfg = deepcopy(source_cfg.arena_builder)
    builder_cfg.num_envs = source_cfg.scene.num_envs
    builder_cfg.env_spacing = source_cfg.scene.env_spacing
    builder_cfg.seed = source_cfg.seed
    builder_cfg.device = source_cfg.sim.device
    builder_cfg.disable_fabric = not source_cfg.sim.use_fabric

    env_cfg, env_kwargs = compile_arena_manager_cfg(
        source_cfg.arena_environment,
        builder_cfg,
        source_cfg.variation_overrides,
    )
    _copy_source_overrides(source_cfg, env_cfg)
    configure_arena_visualizer_defaults(env_cfg)
    source_cfg.arena_environment.scene.validate_simulation_cfg(env_cfg.sim)
    env_cfg._variation_recorder = env_kwargs["variation_recorder"]
    env_cfg._variation_replay_scheduler = env_kwargs["variation_replay_scheduler"]
    return env_cfg
