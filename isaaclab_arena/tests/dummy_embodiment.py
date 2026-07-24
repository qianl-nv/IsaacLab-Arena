# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Lightweight placement embodiment for solver tests."""

from __future__ import annotations

import trimesh
from typing import TYPE_CHECKING

from isaaclab_arena.relations.placement_asset import PlacementAsset
from isaaclab_arena.utils.bounding_box import AxisAlignedBoundingBox
from isaaclab_arena.utils.pose import Pose, PosePerEnv, PoseRange

if TYPE_CHECKING:
    from isaaclab.managers import EventTermCfg


class DummyEmbodiment(PlacementAsset):
    """Embodiment geometry without simulator dependencies."""

    def __init__(
        self,
        name: str,
        bounding_box: AxisAlignedBoundingBox,
        initial_pose: Pose | None = None,
        collision_mesh: trimesh.Trimesh | None = None,
        scene_name: str | None = None,
    ) -> None:
        super().__init__(name=name, tags=["embodiment"])
        self.initial_pose = initial_pose
        self.bounding_box = bounding_box
        self.collision_mesh = collision_mesh
        self.scene_name = name if scene_name is None else scene_name
        self.pose_event_cfg: EventTermCfg | None = None
        if initial_pose is not None:
            self.pose_event_cfg = self._init_pose_event_cfg()

    def get_bounding_box(self) -> AxisAlignedBoundingBox:
        """Return root-relative bounds."""
        return self.bounding_box

    def get_collision_mesh(self) -> trimesh.Trimesh | None:
        """Return the configured collision mesh."""
        return self.collision_mesh

    def _get_initial_pose_as_pose(self) -> Pose | None:
        """Return a single pose for spawn seeding."""
        initial_pose = self.get_initial_pose()
        if initial_pose is None:
            return None
        if isinstance(initial_pose, PosePerEnv):
            return initial_pose.poses[0]
        if isinstance(initial_pose, PoseRange):
            return initial_pose.get_midpoint()
        return initial_pose

    def _set_pose_state(self, pose: Pose | PoseRange | PosePerEnv) -> None:
        """Store the configured pose."""
        assert not isinstance(pose, PoseRange), "DummyEmbodiment does not support PoseRange initial poses"
        self.initial_pose = pose

    def set_initial_pose(self, pose: Pose | PoseRange | PosePerEnv) -> None:
        """Set the embodiment root pose and rebuild the pose reset event."""
        self._set_pose_state(pose)
        self.pose_event_cfg = self._init_pose_event_cfg()

    def set_spawn_pose(self, pose: Pose) -> None:
        """Set the scene-construction pose without rebuilding the pose reset event."""
        self._set_pose_state(pose)

    def has_pose_reset_event(self) -> bool:
        """Return whether the dummy owns a root-pose reset event."""
        return self.pose_event_cfg is not None

    def _init_pose_event_cfg(self) -> EventTermCfg | None:
        """Build the reset event that restores this dummy's root pose."""
        from isaaclab.managers import EventTermCfg

        from isaaclab_arena.terms.events import reset_placement_asset_pose, reset_placement_asset_pose_per_env

        initial_pose = self.get_initial_pose()
        if initial_pose is None:
            return None
        if isinstance(initial_pose, PosePerEnv):
            write_pose_list = [self.layout_pose_to_scene_writes(pose) for pose in initial_pose.poses]
            return EventTermCfg(
                func=reset_placement_asset_pose_per_env,
                mode="reset",
                params={"write_pose_list": write_pose_list},
            )
        if isinstance(initial_pose, Pose):
            return EventTermCfg(
                func=reset_placement_asset_pose,
                mode="reset",
                params={"write_pose_specs": self.layout_pose_to_scene_writes(initial_pose)},
            )
        return None

    def get_scene_name(self) -> str:
        """Return the configured scene key."""
        return self.scene_name
