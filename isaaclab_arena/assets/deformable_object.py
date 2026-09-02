# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Arena deformable object with explicit or USD-authored physics properties."""

from __future__ import annotations

import torch
from typing import Any

from isaaclab.assets import AssetBaseCfg, DeformableObjectCfg
from isaaclab.envs import ManagerBasedEnv
from isaaclab.managers import EventTermCfg, SceneEntityCfg
from isaaclab.sim.spawners.from_files.from_files_cfg import UsdFileCfg
from isaaclab.sim.spawners.meshes.meshes_cfg import MeshCuboidCfg
from isaaclab.sim.spawners.spawner_cfg import DeformableObjectSpawnerCfg
from isaaclab_newton.sim.schemas import NewtonDeformableBodyPropertiesCfg
from isaaclab_physx.sim.schemas import PhysxDeformableBodyPropertiesCfg

from isaaclab_arena.assets.object_base import ObjectBase, ObjectType
from isaaclab_arena.terms.events import set_deformable_object_pose, set_deformable_object_pose_per_env
from isaaclab_arena.utils.bounding_box import AxisAlignedBoundingBox
from isaaclab_arena.utils.pose import Pose, PosePerEnv, PoseRange
from isaaclab_arena.utils.velocity import Velocity


class DeformableObject(ObjectBase):
    """Spawned deformable configured explicitly or by its authored USD schemas."""

    def __init__(
        self,
        name: str,
        spawner_cfg: DeformableObjectSpawnerCfg,
        prim_path: str | None = None,
        initial_pose: Pose | PosePerEnv | None = None,
        local_bounding_box: AxisAlignedBoundingBox | None = None,
        asset_cfg_addon: dict[str, Any] | None = None,
        **kwargs,
    ):
        super().__init__(name=name, prim_path=prim_path, object_type=ObjectType.DEFORMABLE, **kwargs)
        self.spawner_cfg = spawner_cfg
        self.physics_preset = self._infer_physics_preset(spawner_cfg)
        self.asset_cfg_addon = asset_cfg_addon or {}
        self._local_bounding_box = local_bounding_box or self._bounding_box_from_spawner(spawner_cfg)
        self.initial_pose = initial_pose
        self.initial_velocity: Velocity | None = None
        self.object_cfg = self._build_object_cfg()
        self._pose_event_cfg = self._build_reset_event()

    @staticmethod
    def _infer_physics_preset(spawner_cfg: DeformableObjectSpawnerCfg) -> str | None:
        """Infer an explicit backend, or return None for an authored USD."""
        deformable_props = spawner_cfg.deformable_props
        if deformable_props is None:
            assert isinstance(
                spawner_cfg, UsdFileCfg
            ), "Procedural deformable spawners require backend-specific deformable_props"
            return None
        if isinstance(deformable_props, PhysxDeformableBodyPropertiesCfg):
            return "physx"
        if isinstance(deformable_props, NewtonDeformableBodyPropertiesCfg):
            return "newton"
        raise TypeError(f"Unsupported deformable properties type: {type(deformable_props).__name__}")

    @staticmethod
    def _bounding_box_from_spawner(
        spawner_cfg: DeformableObjectSpawnerCfg | None,
    ) -> AxisAlignedBoundingBox | None:
        """Infer undeformed local bounds for a cuboid source."""
        if not isinstance(spawner_cfg, MeshCuboidCfg):
            return None
        half_size = tuple(size * 0.5 for size in spawner_cfg.size)
        return AxisAlignedBoundingBox(
            min_point=tuple(-value for value in half_size),
            max_point=half_size,
        )

    def get_object_cfg(self, physics_preset: str | None = None) -> tuple[str, AssetBaseCfg]:
        """Return the deformable config after checking the selected backend."""
        selected_preset = physics_preset or "physx"
        if self.physics_preset is not None and selected_preset != self.physics_preset:
            raise ValueError(
                f"DeformableObject '{self.name}' is configured for {self.physics_preset!r}, not {selected_preset!r}"
            )
        return self.name, self.object_cfg

    def _build_object_cfg(self) -> DeformableObjectCfg:
        """Build the concrete Isaac Lab deformable config."""
        object_cfg = DeformableObjectCfg(
            prim_path=self.prim_path,
            spawn=self.spawner_cfg,
            **self.asset_cfg_addon,
        )
        initial_pose = self._get_initial_pose_as_pose()
        if initial_pose is not None:
            object_cfg.init_state.pos = initial_pose.position_xyz
            object_cfg.init_state.rot = initial_pose.rotation_xyzw
        return object_cfg

    def _set_initial_pose(self, pose: Pose | PoseRange | PosePerEnv) -> None:
        assert isinstance(pose, (Pose, PosePerEnv)), "Deformables support fixed Pose or PosePerEnv only"
        super()._set_initial_pose(pose)
        initial_pose = self._get_initial_pose_as_pose()
        assert initial_pose is not None
        self.object_cfg.init_state.pos = initial_pose.position_xyz
        self.object_cfg.init_state.rot = initial_pose.rotation_xyzw

    def set_initial_velocity(self, velocity: Velocity) -> None:
        """Set the linear velocity restored by the deformable reset event."""
        self.initial_velocity = velocity
        self._pose_event_cfg = self._build_reset_event()

    def _build_reset_event(self) -> EventTermCfg | None:
        """Build a nodal reset event for the configured centroid pose."""
        if not self.reset_pose or self.initial_pose is None:
            return None
        if isinstance(self.initial_pose, PosePerEnv):
            return EventTermCfg(
                func=set_deformable_object_pose_per_env,
                mode="reset",
                params={"asset_cfg": SceneEntityCfg(self.name), "pose_list": self.initial_pose.poses},
            )
        return EventTermCfg(
            func=set_deformable_object_pose,
            mode="reset",
            params={
                "asset_cfg": SceneEntityCfg(self.name),
                "pose": self.initial_pose,
                "velocity": self.initial_velocity,
            },
        )

    def get_nodal_state(self, env: ManagerBasedEnv) -> torch.Tensor:
        """Return a copy of the current world-frame nodal state."""
        return env.unwrapped.scene[self.name].data.nodal_state_w.torch.clone()

    def get_bounding_box(self) -> AxisAlignedBoundingBox:
        """Return undeformed local bounds used for initial placement."""
        assert self._local_bounding_box is not None, "A local bounding box is required for non-cuboid deformables"
        return self._local_bounding_box
