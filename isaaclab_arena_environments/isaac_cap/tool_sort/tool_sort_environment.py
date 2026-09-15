# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Registered Newton environment for the industrial tool-sort benchmark."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from isaaclab_newton.physics import MJWarpSolverCfg, NewtonCfg, NewtonShapeCfg

from isaaclab_arena.environments.arena_environment_factory import ArenaEnvironmentCfg, ArenaEnvironmentFactory

if TYPE_CHECKING:
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
    from isaaclab_arena.environments.isaaclab_arena_manager_based_env_cfg import IsaacLabArenaManagerBasedRLEnvCfg

_SCENE_SPEC = Path(__file__).with_name("sort_all.yaml")


def configure_tool_sort_physics(
    env_cfg: IsaacLabArenaManagerBasedRLEnvCfg,
) -> IsaacLabArenaManagerBasedRLEnvCfg:
    """Apply the benchmark's 50 Hz, ten-substep Newton configuration."""
    env_cfg.sim.dt = 1.0 / 50.0
    env_cfg.sim.render_interval = 1
    env_cfg.sim.gravity = (0.0, 0.0, -9.81)
    env_cfg.sim.use_newton_actuators = True
    env_cfg.decimation = 1
    env_cfg.sim.physics = NewtonCfg(
        solver_cfg=MJWarpSolverCfg(
            enable_multiccd=True,
            solver="newton",
            integrator="euler",
            nconmax=5000,
            njmax=5000,
            iterations=100,
            ls_iterations=50,
            impratio=20.0,
            cone="elliptic",
            use_mujoco_contacts=True,
        ),
        default_shape_cfg=NewtonShapeCfg(ke=60000.0, kd=500.0, gap=0.002),
        num_substeps=10,
        use_cuda_graph=True,
        debug_mode=False,
    )
    env_cfg.scene.num_envs = 1
    env_cfg.scene.replicate_physics = False
    return env_cfg


@dataclass
class IndustrialToolSortNewtonEnvironmentCfg(ArenaEnvironmentCfg):
    """Configure the industrial FR3 tool-sorting environment."""

    enable_cameras: bool = False
    use_tiled_cameras: bool = False
    embodiment: str | None = None
    """Optional registry name that overrides the graph embodiment."""
    teleop_device: str | None = None
    top_camera_position: list[float] | None = None
    top_camera_rotation_wxyz: list[float] | None = None


class IndustrialToolSortNewtonEnvironment(ArenaEnvironmentFactory[IndustrialToolSortNewtonEnvironmentCfg]):
    """Build tool sorting from its graph and task-owned Newton profile."""

    name = "vabar_tool_sort__sort_all_newton"
    _legacy_argparse_cfg_type = IndustrialToolSortNewtonEnvironmentCfg
    scene_spec = _SCENE_SPEC

    def build(self, cfg: IndustrialToolSortNewtonEnvironmentCfg) -> IsaacLabArenaEnvironment:
        from isaaclab_arena.assets.registries import AssetRegistry, DeviceRegistry
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
        from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment

        spec = ArenaEnvGraphSpec.from_yaml(str(self.scene_spec))
        arena_env = spec.to_arena_env(enable_cameras=cfg.enable_cameras)
        assert isinstance(arena_env, IsaacLabArenaEnvironment)
        if cfg.embodiment is not None:
            arena_env.embodiment = AssetRegistry().get_asset_by_name(cfg.embodiment)(
                enable_cameras=cfg.enable_cameras,
            )
        arena_env.embodiment.set_use_tiled_cameras(cfg.use_tiled_cameras)
        self._configure_top_camera(arena_env.embodiment, cfg)
        if cfg.teleop_device is not None:
            arena_env.teleop_device = DeviceRegistry().get_device_by_name(cfg.teleop_device)()
        arena_env.env_cfg_callback = configure_tool_sort_physics
        return arena_env

    @staticmethod
    def _configure_top_camera(embodiment, cfg: IndustrialToolSortNewtonEnvironmentCfg) -> None:
        """Apply an optional finite top-camera pose override."""
        position_values = cfg.top_camera_position
        rotation_values = cfg.top_camera_rotation_wxyz
        assert (position_values is None) == (
            rotation_values is None
        ), "Top camera position and rotation must be set together."
        if position_values is None or rotation_values is None:
            return
        position = tuple(float(value) for value in position_values)
        rotation = tuple(float(value) for value in rotation_values)
        assert (
            len(position) == 3 and len(rotation) == 4
        ), "Top camera pose must contain three position and four rotation values."
        assert all(math.isfinite(value) for value in (*position, *rotation)), "Top camera pose values must be finite."
        top_camera = embodiment.camera_config.top_camera
        top_camera.offset.pos = position
        top_camera.offset.rot = rotation
