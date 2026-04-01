# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import numpy as np
import torch

import warp as wp
from isaaclab.assets import RigidObject
from isaaclab.managers.recorder_manager import RecorderTerm, RecorderTermCfg
from isaaclab.utils import configclass
from isaaclab.utils.math import combine_frame_transforms

from isaaclab_arena.metrics.metric_base import MetricBase


class MinGoalDistanceRecorder(RecorderTerm):
    """Tracks per-env minimum object-to-goal distance during each episode.

    Updates a running minimum on every post-step and emits the value
    when the episode ends (pre-reset).
    """

    def __init__(self, cfg: "MinGoalDistanceRecorderCfg", env):
        super().__init__(cfg, env)
        self.name = cfg.name
        self._robot_name = cfg.robot_name
        self._object_name = cfg.object_name
        self._command_name = cfg.command_name
        self.first_reset = True
        self._min_dist = torch.full((self._env.num_envs,), float("inf"), device=self._env.device)

    def _compute_distance(self) -> torch.Tensor:
        """Compute object-to-goal L2 distance in world frame for all envs."""
        robot: RigidObject = self._env.scene[self._robot_name]
        obj: RigidObject = self._env.scene[self._object_name]

        command = self._env.command_manager.get_command(self._command_name)
        des_pos_b = command[:, :3]

        root_pos_w = wp.to_torch(robot.data.root_pos_w)
        root_quat_w = wp.to_torch(robot.data.root_quat_w)
        des_pos_w, _ = combine_frame_transforms(root_pos_w, root_quat_w, des_pos_b)

        object_pos_w = wp.to_torch(obj.data.root_pos_w)
        return torch.linalg.norm(des_pos_w - object_pos_w[:, :3], dim=1)

    def record_post_step(self):
        dist = self._compute_distance()
        self._min_dist = torch.minimum(self._min_dist, dist)
        return None, None

    def record_pre_reset(self, env_ids):
        if self.first_reset:
            assert len(env_ids) == self._env.num_envs
            self.first_reset = False
            return None, None

        result = self._min_dist[env_ids].clone()
        self._min_dist[env_ids] = float("inf")
        return self.name, result


@configclass
class MinGoalDistanceRecorderCfg(RecorderTermCfg):
    class_type: type[RecorderTerm] = MinGoalDistanceRecorder
    name: str = "min_goal_distance"
    robot_name: str = "robot"
    object_name: str = "dex_cube"
    command_name: str = "object_pose"


class MinGoalDistanceMetric(MetricBase):
    """Reports mean / min / max of per-episode minimum object-to-goal distance."""

    name = "min_goal_distance"
    recorder_term_name = "min_goal_distance"

    def __init__(self, robot_name: str = "robot", object_name: str = "dex_cube", command_name: str = "object_pose"):
        self._robot_name = robot_name
        self._object_name = object_name
        self._command_name = command_name

    def get_recorder_term_cfg(self) -> RecorderTermCfg:
        return MinGoalDistanceRecorderCfg(
            name=self.recorder_term_name,
            robot_name=self._robot_name,
            object_name=self._object_name,
            command_name=self._command_name,
        )

    def compute_metric_from_recording(self, recorded_metric_data: list[np.ndarray]) -> dict[str, float]:
        if len(recorded_metric_data) == 0:
            return {"mean": float("nan"), "min": float("nan"), "max": float("nan")}
        all_min_dists = np.concatenate(recorded_metric_data)
        finite = all_min_dists[np.isfinite(all_min_dists)]
        if len(finite) == 0:
            return {"mean": float("nan"), "min": float("nan"), "max": float("nan")}
        return {
            "mean": float(np.mean(finite)),
            "min": float(np.min(finite)),
            "max": float(np.max(finite)),
        }
