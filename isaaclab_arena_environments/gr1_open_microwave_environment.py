# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import gymnasium as gym
from dataclasses import dataclass
from typing import TYPE_CHECKING

from isaaclab.scene import InteractiveSceneCfg
from isaaclab.utils.configclass import configclass

from isaaclab_arena.assets.register import register_environment
from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
from isaaclab_arena.environments.arena_environment_factory import ArenaEnvironmentCfg, ArenaEnvironmentFactory
from isaaclab_arena.environments.environment_materializer import _copy_source_overrides
from isaaclab_arena.environments.isaaclab_arena_manager_based_env_cfg import IsaacLabArenaManagerBasedRLEnvCfg
from isaaclab_arena.utils.physics_backend import PhysicsBackend

if TYPE_CHECKING:
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment


@configclass
class Gr1OpenMicrowaveSourceCfg:
    """Serializable authoring inputs for the GR1 open-microwave task."""

    object: str | None = None
    teleop_device: str | None = None
    embodiment: str = "gr1_pink"
    enable_cameras: bool = False


@configclass
class ArenaMaterializationCfg:
    """Arena compiler settings that are not owned by the standard Lab config."""

    solve_relations: bool = True
    placement_seed: int | None = None
    resolve_on_reset: bool | None = None
    mimic: bool = False
    presets: PhysicsBackend | None = None
    language_instruction: str | None = None
    record_trajectories: bool = False
    recorder_dataset_export_dir_path: str | None = None
    recorder_dataset_filename: str | None = None
    recorded_variation_samples_path: str | None = None
    variation_overrides: list[str] | None = None


@configclass
class Gr1OpenMicrowaveEnvCfg(IsaacLabArenaManagerBasedRLEnvCfg):
    """Unmaterialized Lab configuration for the GR1 open-microwave task."""

    scene: InteractiveSceneCfg = InteractiveSceneCfg(
        num_envs=1,
        env_spacing=30.0,
        replicate_physics=False,
    )
    arena_source: Gr1OpenMicrowaveSourceCfg = Gr1OpenMicrowaveSourceCfg()
    arena_materialization: ArenaMaterializationCfg = ArenaMaterializationCfg()


@dataclass
class Gr1OpenMicrowaveEnvironmentCfg(ArenaEnvironmentCfg):
    """Configure the GR1 open-microwave environment."""

    object: str | None = None
    teleop_device: str | None = None
    embodiment: str = "gr1_pink"


@register_environment
class Gr1OpenMicrowaveEnvironment(ArenaEnvironmentFactory[Gr1OpenMicrowaveEnvironmentCfg]):

    name: str = "gr1_open_microwave"
    _legacy_argparse_cfg_type = Gr1OpenMicrowaveEnvironmentCfg

    def build(self, cfg: Gr1OpenMicrowaveEnvironmentCfg) -> IsaacLabArenaEnvironment:
        """Build the environment from its typed configuration."""
        return build_gr1_open_microwave_environment(
            Gr1OpenMicrowaveSourceCfg(
                object=cfg.object,
                teleop_device=cfg.teleop_device,
                embodiment=cfg.embodiment,
                enable_cameras=cfg.enable_cameras,
            )
        )


def build_gr1_open_microwave_environment(source: Gr1OpenMicrowaveSourceCfg) -> IsaacLabArenaEnvironment:
    """Build the compiler-local Arena graph for the GR1 open-microwave task."""
    from isaaclab_arena.assets.registries import AssetRegistry, DeviceRegistry
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
    from isaaclab_arena.environments.isaaclab_arena_manager_based_env_cfg import set_control_rate_50hz
    from isaaclab_arena.scene.scene import Scene
    from isaaclab_arena.tasks.open_door_task import OpenDoorTask
    from isaaclab_arena.utils.pose import Pose

    asset_registry = AssetRegistry()
    background = asset_registry.get_asset_by_name("kitchen")()
    microwave = asset_registry.get_asset_by_name("microwave")()
    assets = [background, microwave]
    assert source.embodiment in ["gr1_pink", "gr1_joint"], f"Invalid GR1T2 embodiment {source.embodiment}"
    embodiment = asset_registry.get_asset_by_name(source.embodiment)(enable_cameras=source.enable_cameras)
    embodiment.set_initial_pose(Pose(position_xyz=(-0.4, 0.0, 0.0), rotation_xyzw=(0.0, 0.0, 0.0, 1.0)))

    teleop_device = (
        DeviceRegistry().get_device_by_name(source.teleop_device)() if source.teleop_device is not None else None
    )

    microwave.set_initial_pose(
        Pose(
            position_xyz=(0.4, -0.00586, 0.22773),
            rotation_xyzw=(0, 0, -0.7071068, 0.7071068),
        )
    )

    if source.object is not None:
        extra_object = asset_registry.get_asset_by_name(source.object)()
        extra_object.set_initial_pose(
            Pose(
                position_xyz=(0.466, -0.437, 0.154),
                rotation_xyzw=(-0.5, 0.5, -0.5, 0.5),
            )
        )
        assets.append(extra_object)

    return IsaacLabArenaEnvironment(
        name=Gr1OpenMicrowaveEnvironment.name,
        embodiment=embodiment,
        scene=Scene(assets=assets),
        task=OpenDoorTask(microwave, openness_threshold=0.8, reset_openness=0.2, episode_length_s=5.0),
        teleop_device=teleop_device,
        env_cfg_callback=set_control_rate_50hz,
    )


def _builder_cfg_from_source(cfg: Gr1OpenMicrowaveEnvCfg) -> ArenaEnvBuilderCfg:
    """Translate standard Lab and Arena materialization fields into compiler settings."""
    materialization = cfg.arena_materialization
    return ArenaEnvBuilderCfg(
        num_envs=cfg.scene.num_envs,
        env_spacing=cfg.scene.env_spacing,
        seed=cfg.seed,
        solve_relations=materialization.solve_relations,
        placement_seed=materialization.placement_seed,
        resolve_on_reset=materialization.resolve_on_reset,
        disable_fabric=not cfg.sim.use_fabric,
        mimic=materialization.mimic,
        presets=materialization.presets,
        device=cfg.sim.device,
        language_instruction=materialization.language_instruction,
        record_trajectories=materialization.record_trajectories,
        recorder_dataset_export_dir_path=materialization.recorder_dataset_export_dir_path,
        recorder_dataset_filename=materialization.recorder_dataset_filename,
        recorded_variation_samples_path=materialization.recorded_variation_samples_path,
    )


def make_gr1_open_microwave_env_cfg(
    legacy_cfg: Gr1OpenMicrowaveEnvironmentCfg | None = None,
    builder_cfg: ArenaEnvBuilderCfg | None = None,
) -> Gr1OpenMicrowaveEnvCfg:
    """Create a serializable source config from optional legacy inputs."""
    cfg = Gr1OpenMicrowaveEnvCfg()
    if legacy_cfg is not None:
        cfg.arena_source = Gr1OpenMicrowaveSourceCfg(
            object=legacy_cfg.object,
            teleop_device=legacy_cfg.teleop_device,
            embodiment=legacy_cfg.embodiment,
            enable_cameras=legacy_cfg.enable_cameras,
        )
    if builder_cfg is not None:
        cfg.scene.num_envs = builder_cfg.num_envs
        cfg.scene.env_spacing = builder_cfg.env_spacing
        cfg.seed = builder_cfg.seed
        cfg.sim.device = builder_cfg.device
        cfg.sim.use_fabric = not builder_cfg.disable_fabric
        cfg.arena_materialization = ArenaMaterializationCfg(
            solve_relations=builder_cfg.solve_relations,
            placement_seed=builder_cfg.placement_seed,
            resolve_on_reset=builder_cfg.resolve_on_reset,
            mimic=builder_cfg.mimic,
            presets=builder_cfg.presets,
            language_instruction=builder_cfg.language_instruction,
            record_trajectories=builder_cfg.record_trajectories,
            recorder_dataset_export_dir_path=builder_cfg.recorder_dataset_export_dir_path,
            recorder_dataset_filename=builder_cfg.recorder_dataset_filename,
            recorded_variation_samples_path=builder_cfg.recorded_variation_samples_path,
        )
    cfg.__arena_defaults__ = cfg.to_dict()
    return cfg


def materialize_gr1_open_microwave_env_cfg(
    source_cfg: Gr1OpenMicrowaveEnvCfg,
) -> IsaacLabArenaManagerBasedRLEnvCfg:
    """Compile the Open Microwave source after Lab has applied overrides."""
    from isaaclab_arena.environments.arena_env_compiler import (
        compile_arena_manager_cfg,
        configure_arena_visualizer_defaults,
    )

    arena_env = build_gr1_open_microwave_environment(source_cfg.arena_source)
    env_cfg, env_kwargs = compile_arena_manager_cfg(
        arena_env,
        _builder_cfg_from_source(source_cfg),
        source_cfg.arena_materialization.variation_overrides,
    )
    _copy_source_overrides(source_cfg, env_cfg)
    configure_arena_visualizer_defaults(env_cfg)
    arena_env.scene.validate_simulation_cfg(env_cfg.sim)
    env_cfg._variation_recorder = env_kwargs["variation_recorder"]
    env_cfg._variation_replay_scheduler = env_kwargs["variation_replay_scheduler"]
    return env_cfg


def register_gr1_open_microwave_gym_task() -> None:
    """Register the Gym-native materialized task unless a real registration already exists."""
    task_name = Gr1OpenMicrowaveEnvironment.name
    existing = gym.registry.get(task_name)
    if existing is not None and not existing.kwargs.get("_arena_rl_discovery_placeholder", False):
        return
    if existing is not None:
        del gym.registry[task_name]
    gym.register(
        id=task_name,
        entry_point="isaaclab_arena.environments.isaaclab_arena_manager_based_env:IsaacLabArenaManagerBasedRLEnv",
        kwargs={
            "env_cfg_entry_point": make_gr1_open_microwave_env_cfg,
            "env_cfg_materializer_entry_point": (
                "isaaclab_arena_environments.gr1_open_microwave_environment:materialize_gr1_open_microwave_env_cfg"
            ),
        },
        disable_env_checker=True,
    )


register_gr1_open_microwave_gym_task()
