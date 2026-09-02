# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Shared lifecycle for objects represented by a root transform."""

from __future__ import annotations

import torch
from abc import abstractmethod

import warp as wp
from isaaclab.assets import ArticulationCfg, AssetBaseCfg, RigidObjectCfg
from isaaclab.envs import ManagerBasedEnv
from isaaclab.managers import EventTermCfg, SceneEntityCfg
from isaaclab.sensors.contact_sensor.contact_sensor_cfg import ContactSensorCfg
from isaaclab.sim.views import FrameView
from isaaclab_tasks.contrib.stack.mdp.franka_stack_events import randomize_object_pose

from isaaclab_arena.assets.object_base import ObjectBase, ObjectType
from isaaclab_arena.terms.events import set_object_pose, set_object_pose_per_env
from isaaclab_arena.utils.pose import Pose, PosePerEnv, PoseRange
from isaaclab_arena.utils.velocity import Velocity
from isaaclab_arena.variations.object_mass_variation import ObjectMassVariation


class RootedObjectBase(ObjectBase):
    """Base class for rigid, articulated, and static rooted objects."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.object_type == ObjectType.RIGID:
            self.add_variation(ObjectMassVariation(self.name))
        self.initial_velocity: Velocity | None = None
        self._base_frame_view: FrameView | None = None
        self._base_frame_view_stage = None

    def get_object_cfg(self) -> tuple[str, AssetBaseCfg]:
        """Return the scene key and eagerly materialized rooted-object config."""
        return self.name, self.object_cfg

    def _close_base_frame_view(self) -> None:
        """Release the cached frame view. Safe to call more than once."""
        frame_view = getattr(self, "_base_frame_view", None)
        if frame_view is not None:
            frame_view.close()
            self._base_frame_view = None
            self._base_frame_view_stage = None

    def __del__(self):
        """Release the cached frame view when this object is dropped."""
        self._close_base_frame_view()

    def _set_initial_pose(self, pose: Pose | PoseRange | PosePerEnv) -> None:
        """Store the pose and write its construction values into the object config."""
        super()._set_initial_pose(pose)
        initial_pose = self._get_initial_pose_as_pose()
        object_cfg = getattr(self, "object_cfg", None)
        if initial_pose is not None and object_cfg is not None:
            object_cfg.init_state.pos = initial_pose.position_xyz
            object_cfg.init_state.rot = initial_pose.rotation_xyzw

    def set_initial_velocity(self, velocity: Velocity) -> None:
        """Set the initial velocity on the object config and its reset event."""
        self.initial_velocity = velocity
        object_cfg = getattr(self, "object_cfg", None)
        if object_cfg is not None and hasattr(object_cfg.init_state, "lin_vel"):
            object_cfg.init_state.lin_vel = velocity.linear_xyz
        if object_cfg is not None and hasattr(object_cfg.init_state, "ang_vel"):
            object_cfg.init_state.ang_vel = velocity.angular_xyz
        self._pose_event_cfg = self._build_reset_event()

    def _requires_reset_pose_event(self) -> bool:
        """Return whether this representation supports an initial-pose reset."""
        return self.get_initial_pose() is not None and self.object_type in (
            ObjectType.RIGID,
            ObjectType.ARTICULATION,
        )

    def _build_reset_event(self) -> EventTermCfg | None:
        """Build the event that restores this object's pose and velocity."""
        if not self._requires_reset_pose_event():
            return None

        initial_pose = self.get_initial_pose()
        if isinstance(initial_pose, PosePerEnv):
            return EventTermCfg(
                func=set_object_pose_per_env,
                mode="reset",
                params={
                    "asset_cfg": SceneEntityCfg(self.name),
                    "pose_list": initial_pose.poses,
                },
            )
        if isinstance(initial_pose, PoseRange):
            return EventTermCfg(
                func=randomize_object_pose,
                mode="reset",
                params={
                    "pose_range": initial_pose.to_dict(),
                    "asset_cfgs": [SceneEntityCfg(self.name)],
                },
            )
        return EventTermCfg(
            func=set_object_pose,
            mode="reset",
            params={
                "pose": initial_pose,
                "asset_cfg": SceneEntityCfg(self.name),
                "velocity": self.initial_velocity,
            },
        )

    def _init_object_cfg(self) -> AssetBaseCfg:
        if self.object_type == ObjectType.RIGID:
            return self._generate_rigid_cfg()
        if self.object_type == ObjectType.ARTICULATION:
            return self._generate_articulation_cfg()
        if self.object_type == ObjectType.BASE:
            return self._generate_base_cfg()
        raise ValueError(f"Invalid rooted object type: {self.object_type}")

    def get_object_pose(self, env: ManagerBasedEnv, is_relative: bool = True) -> torch.Tensor:
        """Return the object's root pose in world or environment-relative coordinates."""
        assert self.name in env.unwrapped.scene.keys(), f"Asset {self.name} not found in scene"
        if self.object_type in (ObjectType.RIGID, ObjectType.ARTICULATION):
            object_pose = wp.to_torch(env.unwrapped.scene[self.name].data.root_pose_w).clone()
        elif self.object_type == ObjectType.BASE:
            scene = env.unwrapped.scene
            stage = scene.stage
            if self._base_frame_view is None or self._base_frame_view_stage is not stage:
                self._close_base_frame_view()
                asset_cfg = scene[self.name]
                frame_view = FrameView(asset_cfg.prim_path, device=env.unwrapped.device, stage=stage)
                try:
                    prim_paths = frame_view.prim_paths
                    assert len(prim_paths) == env.unwrapped.num_envs, (
                        f"AssetBaseCfg scene entry '{self.name}' resolved to {len(prim_paths)} prims; "
                        f"expected {env.unwrapped.num_envs}."
                    )
                    for environment_id, prim_path in enumerate(prim_paths):
                        environment_prim_path = scene.env_prim_paths[environment_id]
                        assert str(prim_path).startswith(f"{environment_prim_path}/"), (
                            f"AssetBaseCfg scene entry '{self.name}' pose row {environment_id} belongs to"
                            f" '{prim_path}', not environment '{environment_prim_path}'."
                        )
                except Exception:
                    frame_view.close()
                    raise
                self._base_frame_view = frame_view
                self._base_frame_view_stage = stage
            position_w, orientation_w = self._base_frame_view.get_world_poses()
            object_pose = torch.cat((position_w.torch, orientation_w.torch), dim=-1)
        else:
            raise ValueError(f"Function not implemented for object type: {self.object_type}")
        if is_relative:
            object_pose[:, :3] -= env.unwrapped.scene.env_origins
        return object_pose

    def set_object_pose(self, env: ManagerBasedEnv, pose: Pose, env_ids: torch.Tensor | None = None) -> None:
        """Set the object's root pose and zero velocity in selected environments."""
        env = env.unwrapped
        assert self.name in env.scene.keys(), f"Asset {self.name} not found in scene"
        if env_ids is None:
            env_ids = torch.arange(env.num_envs, device=env.device)
        set_object_pose(env, env_ids, SceneEntityCfg(self.name), pose)

    def get_contact_sensor_cfg(
        self,
        contact_against_object: ObjectBase | None = None,
    ) -> ContactSensorCfg:
        """Build a contact sensor config for a rigid rooted object."""
        assert self.object_type == ObjectType.RIGID, "Contact sensor is only supported for rigid objects"
        filter_prim_paths = [contact_against_object.get_prim_path()] if contact_against_object else []
        return ContactSensorCfg(
            prim_path=self.prim_path,
            filter_prim_paths_expr=filter_prim_paths,
        )

    @abstractmethod
    def _generate_rigid_cfg(self) -> RigidObjectCfg:
        """Build the rigid-object config."""

    @abstractmethod
    def _generate_articulation_cfg(self) -> ArticulationCfg:
        """Build the articulation config."""

    @abstractmethod
    def _generate_base_cfg(self) -> AssetBaseCfg:
        """Build the static-asset config."""
