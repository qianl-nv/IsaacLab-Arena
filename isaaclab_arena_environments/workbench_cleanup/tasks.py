# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Containment and plug-withdrawal tasks for the workbench scene."""

from functools import partial

from isaaclab_arena.assets.asset import Asset
from isaaclab_arena.assets.register import register_task
from isaaclab_arena.metrics.success_rate import SuccessRateMetric
from isaaclab_arena.progress_tracking.completion_criteria import CompletionCriteria
from isaaclab_arena.tasks.object_in_task import ObjectInTask
from isaaclab_arena.tasks.predicates.spatial import (
    depth_in_range,
    lateral_in_proximity,
    object_in_contact_with_target,
    velocity_below_threshold,
)
from isaaclab_arena.tasks.predicates.temporal import TrueForConsecutiveStepsCfg
from isaaclab_arena.tasks.task_base import TaskBase
from isaaclab_arena.tasks.task_termination_cfg import TaskTerminationCfg
from isaaclab_arena.utils.bounding_box import AxisAlignedBoundingBox


@register_task
class ClosedCaseInDrawerTask(ObjectInTask):
    """Apply ObjectInTask's contact and settling checks to the closed articulated case.

    Arena's cached rigid geometry query excludes articulations. The case's authored
    closed bounds are valid here because the lid must be closed simultaneously.
    """

    def _contained(self, env):
        T_W_C = env.arena_world.get_pose_w(self.object.name)
        bounds_C = self.object.get_bounding_box().to(env.device)
        bounds_W = bounds_C.transformed(T_W_C[:, :3], T_W_C[:, 3:]).to_aabb()
        drawer_W = env.arena_world.get_aabb_w(self.target.name)
        contained = bounds_W.volume_fraction_within(drawer_W) >= self.minimum_contained_fraction
        return contained & self.object.is_closed(env, threshold=0.05)

    def _settled_inside(self, env):
        return (
            self._contained(env)
            & object_in_contact_with_target(env, self.contact_sensor_cfg, self.contact_force_threshold)
            & velocity_below_threshold(
                env, self.object.name, self.linear_velocity_threshold, self.angular_velocity_threshold
            )
        )

    def get_termination_cfg(self):
        return TaskTerminationCfg(
            timeout_s=self.episode_length_s,
            success=[
                CompletionCriteria(
                    name="closed_case_in_drawer",
                    predicate_sequence=[
                        self._contained,
                        TrueForConsecutiveStepsCfg(
                            predicate=self._settled_inside,
                            required_steps=self.consecutive_success_steps,
                        ),
                    ],
                )
            ],
        )


@register_task
class ToolInBinTask(ObjectInTask):
    """Require the complete tool hull inside the bin, with contact and settling.

    Rotating an enclosing local box invents empty corners below a resting tapered
    tool. Transforming the hull vertices gives the actual world-space bounds.
    """

    def _contained(self, env):
        import torch

        from isaaclab.utils.math import quat_apply

        T_W_O = env.arena_world.get_pose_w(self.object.name)
        vertices_O = torch.as_tensor(self.object.hull_vertices_O, dtype=torch.float32, device=env.device)
        vertices_O = vertices_O[None].expand(env.num_envs, -1, -1)
        q_W_O = T_W_O[:, None, 3:].expand(-1, vertices_O.shape[1], -1)
        vertices_W = quat_apply(q_W_O, vertices_O) + T_W_O[:, None, :3]
        bounds_W = AxisAlignedBoundingBox(vertices_W.amin(dim=1), vertices_W.amax(dim=1))
        bin_W = env.arena_world.get_aabb_w(self.target.name)
        return bounds_W.volume_fraction_within(bin_W) >= self.minimum_contained_fraction

    def _settled_inside(self, env):
        return (
            self._contained(env)
            & object_in_contact_with_target(env, self.contact_sensor_cfg, self.contact_force_threshold)
            & velocity_below_threshold(
                env, self.object.name, self.linear_velocity_threshold, self.angular_velocity_threshold
            )
        )

    def get_termination_cfg(self):
        return TaskTerminationCfg(
            timeout_s=self.episode_length_s,
            success=[
                CompletionCriteria(
                    name="tool_in_bin",
                    predicate_sequence=[
                        self._contained,
                        TrueForConsecutiveStepsCfg(
                            predicate=self._settled_inside,
                            required_steps=self.consecutive_success_steps,
                        ),
                    ],
                )
            ],
        )


def plug_withdrawn(env, plug_name, outlet_name, minimum_distance):
    """Require axial clearance from the outlet and a stopped plug."""
    clear = depth_in_range(
        env,
        plug_name,
        outlet_name,
        (0, 0, 0),
        minimum_distance,
        None,
        receiver_axis=(1, 0, 0),
    )
    return clear & velocity_below_threshold(env, plug_name, 0.03, 0.1)


def plug_seated(env, plug_name, outlet_name):
    """Check insertion depth and alignment with the outlet opening."""
    return depth_in_range(
        env,
        plug_name,
        outlet_name,
        (0, 0, 0.03),
        0.02,
        0.07,
        receiver_axis=(1, 0, 0),
    ) & lateral_in_proximity(
        env,
        plug_name,
        outlet_name,
        (0, 0, 0.03),
        0.015,
        receiver_axis=(1, 0, 0),
    )


@register_task
class UnplugTask(TaskBase):
    """Withdraw a previously seated plug along the outlet's outward X axis."""

    def __init__(
        self,
        plug: Asset,
        outlet: Asset,
        minimum_distance: float = 0.12,
        consecutive_success_steps: int = 10,
        episode_length_s: float = 60.0,
    ):
        super().__init__(episode_length_s=episode_length_s)
        assert minimum_distance > 0.07
        self.plug = plug
        self.outlet = outlet
        self.minimum_distance = minimum_distance
        self.consecutive_success_steps = consecutive_success_steps

    def get_termination_cfg(self):
        return TaskTerminationCfg(
            timeout_s=self.episode_length_s,
            success=[
                CompletionCriteria(
                    name="unplug",
                    predicate_sequence=[
                        partial(
                            plug_seated,
                            plug_name=self.plug.name,
                            outlet_name=self.outlet.name,
                        ),
                        TrueForConsecutiveStepsCfg(
                            predicate=partial(
                                plug_withdrawn,
                                plug_name=self.plug.name,
                                outlet_name=self.outlet.name,
                                minimum_distance=self.minimum_distance,
                            ),
                            required_steps=self.consecutive_success_steps,
                        ),
                    ],
                )
            ],
        )

    def get_scene_cfg(self):
        return None

    def get_events_cfg(self):
        return None

    def get_mimic_env_cfg(self, arm_mode):
        return None

    def get_metrics(self):
        return [SuccessRateMetric()]
