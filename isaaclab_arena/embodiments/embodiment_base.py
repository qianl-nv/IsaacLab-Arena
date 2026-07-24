# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from isaaclab.envs import ManagerBasedRLMimicEnv
from isaaclab.managers.recorder_manager import RecorderManagerBaseCfg

from isaaclab_arena.embodiments.common.arm_mode import ArmMode
from isaaclab_arena.relations.placement_asset import PlacementAsset
from isaaclab_arena.utils.bounding_box import AxisAlignedBoundingBox
from isaaclab_arena.utils.cameras import ArenaCameraCfg, make_camera_observation_cfg
from isaaclab_arena.utils.configclass import combine_configclass_instances, make_configclass
from isaaclab_arena.utils.pose import Pose, PosePerEnv, PoseRange

if TYPE_CHECKING:
    from isaaclab.managers import EventTermCfg

ROBOT_POSE_RESET_EVENT_NAME = "robot_reset_pose"


class EmbodimentBase(PlacementAsset):

    name: str | None = None
    tags: list[str] = ["embodiment"]
    default_arm_mode: ArmMode | None = None

    def __init__(
        self,
        enable_cameras: bool = False,
        initial_pose: Pose | None = None,
        concatenate_observation_terms: bool = False,
        arm_mode: ArmMode | None = None,
    ):
        assert self.name is not None, "Embodiment name is required"
        super().__init__(name=self.name, tags=self.tags)
        if "embodiment" not in self.tags:
            self.tags.append("embodiment")
        self.enable_cameras = enable_cameras
        self.initial_pose = initial_pose
        self.concatenate_observation_terms = concatenate_observation_terms
        self.arm_mode = arm_mode or self.default_arm_mode
        # These should be filled by the subclass
        self.scene_config: Any | None = None
        self.camera_config: Any | None = None
        self.action_config: Any | None = None
        self.observation_config: Any | None = None
        self.event_config: Any | None = None
        self.reward_config: Any | None = None
        self.curriculum_config: Any | None = None
        self.command_config: Any | None = None
        self.mimic_env: Any | None = None
        self.xr: Any | None = None
        self.termination_cfg: Any | None = None
        self.pose_event_cfg: EventTermCfg | None = None

    def get_bounding_box(self) -> AxisAlignedBoundingBox:
        """Return root-relative bounds computed from the articulation's USD geometry."""
        # Import locally because USD/pxr is available only after simulation initialization.
        from isaaclab_arena.utils.usd_helpers import compute_local_bounding_box_from_usd

        assert self.scene_config is not None, "scene_config must be populated before placement"
        robot = self.scene_config.robot
        assert robot is not None, "scene_config.robot must be populated before placement"
        spawn = robot.spawn
        assert spawn.usd_path is not None, "scene_config.robot must use a USD spawn for placement"
        scale = tuple(spawn.scale or (1.0, 1.0, 1.0))
        # TODO(zihaox): Account for configured initial joint positions in bounds and collision meshes.
        return compute_local_bounding_box_from_usd(spawn.usd_path, scale)

    def _get_initial_pose_as_pose(self) -> Pose | None:
        """Return a single pose for scene construction and bounding-box helpers."""
        initial_pose = self.get_initial_pose()
        if initial_pose is None:
            return None
        if isinstance(initial_pose, PosePerEnv):
            return initial_pose.poses[0]
        if isinstance(initial_pose, PoseRange):
            return initial_pose.get_midpoint()
        return initial_pose

    def _set_pose_state(self, pose: Pose | PoseRange | PosePerEnv) -> None:
        """Update the stored pose and materialize the scene construction config."""
        assert not isinstance(pose, PoseRange), "Embodiments do not support PoseRange initial poses"
        self.initial_pose = pose
        initial_pose = self._get_initial_pose_as_pose()
        if initial_pose is not None and self.scene_config is not None:
            self.scene_config = self._update_scene_cfg_with_robot_initial_pose(self.scene_config, initial_pose)

    def set_initial_pose(self, pose: Pose | PoseRange | PosePerEnv) -> None:
        """Set the embodiment root pose and rebuild the pose reset event."""
        self._set_pose_state(pose)
        self.pose_event_cfg = self._init_pose_event_cfg()

    def set_spawn_pose(self, pose: Pose) -> None:
        """Set the scene-construction pose without rebuilding the pose reset event."""
        assert self.scene_config is not None, "scene_config must be populated before setting the spawn pose"
        self._set_pose_state(pose)

    def supports_per_env_initial_pose(self) -> bool:
        """Return True because embodiment reset events can restore per-environment poses."""
        return True

    def has_pose_reset_event(self) -> bool:
        """Return whether the embodiment owns a root-pose reset event."""
        return self.pose_event_cfg is not None

    def _build_write_pose_specs(self, pose: Pose) -> list[tuple[str, Pose]]:
        """Return precomputed scene writes for one layout pose."""
        return self.layout_pose_to_scene_writes(pose)

    def _init_pose_event_cfg(self) -> EventTermCfg | None:
        """Build the reset event that restores this embodiment's root pose."""
        from isaaclab.managers import EventTermCfg

        from isaaclab_arena.terms.events import reset_placement_asset_pose, reset_placement_asset_pose_per_env

        initial_pose = self.get_initial_pose()
        if initial_pose is None:
            return None
        if isinstance(initial_pose, PosePerEnv):
            write_pose_list = [self._build_write_pose_specs(pose) for pose in initial_pose.poses]
            return EventTermCfg(
                func=reset_placement_asset_pose_per_env,
                mode="reset",
                params={"write_pose_list": write_pose_list},
            )
        if isinstance(initial_pose, Pose):
            return EventTermCfg(
                func=reset_placement_asset_pose,
                mode="reset",
                params={"write_pose_specs": self._build_write_pose_specs(initial_pose)},
            )
        return None

    def set_joint_initial_pos(self, joint_pos: Mapping[str, float]) -> None:
        """Update the robot's initial joint positions by joint name."""
        assert self.scene_config is not None, "scene_config must be populated before setting joint positions"
        robot = self.scene_config.robot
        assert robot is not None, "scene_config.robot must be populated before setting joint positions"
        robot.init_state.joint_pos.update(joint_pos)

    def get_scene_cfg(self) -> Any:
        initial_pose = self._get_initial_pose_as_pose()
        if initial_pose is not None:
            self.scene_config = self._update_scene_cfg_with_robot_initial_pose(self.scene_config, initial_pose)
        if self.enable_cameras:
            if self.camera_config is not None:
                return combine_configclass_instances(
                    "SceneCfg",
                    self.scene_config,
                    self.get_camera_cfg(),
                )
        return self.scene_config

    def get_action_cfg(self) -> Any:
        return self.action_config

    def get_observation_cfg(self) -> Any:
        if self.enable_cameras:
            if self.camera_config is not None:
                camera_observation_config = make_camera_observation_cfg(self.camera_config)
                return combine_configclass_instances(
                    "ObservationCfg",
                    self.observation_config,
                    camera_observation_config,
                )
        return self.observation_config

    def get_rewards_cfg(self) -> Any:
        return self.reward_config

    def get_curriculum_cfg(self) -> Any:
        return self.curriculum_config

    def get_commands_cfg(self) -> Any:
        return self.command_config

    def get_events_cfg(self) -> Any:
        from isaaclab.managers import EventTermCfg

        if self.pose_event_cfg is None:
            return self.event_config
        pose_event_cfg = make_configclass(
            "EmbodimentPoseEventCfg",
            [(ROBOT_POSE_RESET_EVENT_NAME, EventTermCfg, self.pose_event_cfg)],
        )()
        if self.event_config is None:
            return pose_event_cfg
        return combine_configclass_instances("EmbodimentEventsCfg", self.event_config, pose_event_cfg)

    def get_mimic_env(self) -> ManagerBasedRLMimicEnv:
        return self.mimic_env

    def get_xr_cfg(self) -> Any:
        return self.xr

    def get_teleop_target_frame_prim_path(self) -> str | None:
        """Optional USD prim path for rebasing teleop poses (e.g. robot base link). Returns None if not set."""

    def get_camera_cfg(self) -> Any:
        if self.camera_config is None:
            return None
        # In Arena we expect camera configs to inherit from ArenaCameraCfg.
        assert isinstance(
            self.camera_config, ArenaCameraCfg
        ), f"Expected camera_config to inherit from ArenaCameraCfg; got {type(self.camera_config).__name__}."
        return self.camera_config.get_cfg()

    def add_camera_variations(self, camera_rig: ArenaCameraCfg) -> None:
        """Register extrinsics and intrinsics variations for every camera in ``camera_rig``."""
        from isaaclab_arena.variations.camera_extrinsics_variation import CameraExtrinsicsVariation
        from isaaclab_arena.variations.camera_intrinsics_variation import CameraIntrinsicsVariation

        for camera_name in camera_rig.camera_names():
            self.add_variation(CameraExtrinsicsVariation(camera_name=camera_name))
            self.add_variation(CameraIntrinsicsVariation(camera_name=camera_name, camera_rig=camera_rig))

    def _update_scene_cfg_with_robot_initial_pose(self, scene_config: Any, pose: Pose) -> Any:
        assert scene_config is not None, "scene_config must be populated before setting the root pose"
        robot = scene_config.robot
        assert robot is not None, "scene_config.robot must be populated before setting the root pose"
        for scene_name, write_pose in self.layout_pose_to_scene_writes(pose):
            if scene_name == self.get_embodiment_name_in_scene():
                robot.init_state.pos = write_pose.position_xyz
                robot.init_state.rot = write_pose.rotation_xyzw
        return scene_config

    def get_recorder_term_cfg(self) -> RecorderManagerBaseCfg:
        return None

    def get_termination_cfg(self) -> Any:
        return self.termination_cfg

    def get_embodiment_name_in_scene(self) -> str:
        return "robot"

    def get_scene_name(self) -> str:
        """Return the embodiment's Isaac Lab scene key."""
        return self.get_embodiment_name_in_scene()

    def get_ee_frame_name(self, arm_mode: ArmMode) -> str:
        # In case of multiple ee frames one can use self.mimic_arm_mode to get the correct ee frame name
        return ""

    def get_command_body_name(self) -> str:
        return ""

    def get_arm_mode(self) -> ArmMode:
        return self.arm_mode
