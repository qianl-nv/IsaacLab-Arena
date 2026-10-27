# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Reusable force controller that advances environments through ``env.step()``."""

from __future__ import annotations

import contextlib
import dataclasses
import torch
from typing import Any

from isaaclab.utils.math import compute_pose_error, quat_apply, quat_apply_inverse, quat_mul

from isaaclab_arena.agentic_environment_generation.force.commands import (
    AssertCommand,
    FinishCommand,
    ForceCommand,
    InspectCommand,
    JointEffortToCommand,
    MoveCommand,
    ReleaseAllCommand,
    ReleaseCommand,
    WaitCommand,
)
from isaaclab_arena.policy.zero_action_policy import ZeroActionPolicy, ZeroActionPolicyCfg


class ForceController:
    """Execute bounded physical-force commands through the environment lifecycle."""

    def __init__(self, env, observation, *, max_steps: int = 100_000) -> None:
        self.env = env
        self.base_env = env.unwrapped
        assert self.base_env.num_envs == 1, "Force authoring currently supports exactly one environment."
        self.observation = observation
        self.max_steps = max_steps
        self.policy = ZeroActionPolicy(ZeroActionPolicyCfg())
        self.policy.reset()
        self.steps = 0
        self.finished = False
        self.trace: list[dict[str, Any]] = []
        self._pose_holds: dict[str, dict[str, Any]] = {}
        self._joint_holds: dict[tuple[str, str], dict[str, float]] = {}
        self._joint_gain_defaults: dict[tuple[str, str], tuple[torch.Tensor, torch.Tensor]] = {}
        self._last_wrenches: dict[str, dict[str, Any]] = {}

    @property
    def step_dt(self) -> float:
        """Return one policy control-step duration."""
        return float(self.base_env.step_dt)

    def execute(self, command: ForceCommand) -> dict[str, Any]:
        """Execute one validated command and return its acknowledgement."""
        assert not self.finished, "The force session is already finished."
        start_step = self.steps
        if isinstance(command, MoveCommand):
            details = self._move(command)
        elif isinstance(command, JointEffortToCommand):
            details = self._joint_effort_to(command)
        elif isinstance(command, ReleaseCommand):
            self.release(command.object_name)
            details = {"released": command.object_name}
        elif isinstance(command, ReleaseAllCommand):
            self.release_all()
            details = {"released_all": True}
        elif isinstance(command, WaitCommand):
            self._step_for_seconds(command.duration_s)
            details = {"duration_s": command.duration_s}
        elif isinstance(command, InspectCommand):
            details = self.inspect(command.objects)
        elif isinstance(command, AssertCommand):
            details = self._assert_condition(command)
        elif isinstance(command, FinishCommand):
            self.finished = True
            details = {"finished": True}
        else:
            raise TypeError(f"Unsupported force command: {type(command).__name__}")
        acknowledgement = {
            "command_id": command.command_id,
            "action": command.action,
            "status": "completed",
            "start_step": start_step,
            "end_step": self.steps,
            "result": details,
        }
        self.trace.append({
            "command_id": command.command_id,
            "action": command.action,
            "start_step": start_step,
            "end_step": self.steps,
            "task_success": (
                bool(self.base_env.progress_tracker.is_complete()[0].item())
                if hasattr(self.base_env, "progress_tracker")
                else None
            ),
        })
        return acknowledgement

    def _move(self, command: MoveCommand) -> dict[str, Any]:
        name = command.object_name
        self._require_wrench_object(name)
        T_W_O_start = self.base_env.arena_world.get_pose_w(name).clone()
        t_W_goal, q_W_goal = self._pose_goal(command, T_W_O_start)
        control_steps = max(1, round(command.duration_s / self.step_dt))
        for index in range(control_steps):
            alpha = torch.tensor((index + 1) / control_steps, device=self.base_env.device)
            alpha = alpha * alpha * (3.0 - 2.0 * alpha)
            self._pose_holds[name] = {
                "t_W_goal": (1.0 - alpha) * T_W_O_start[:, :3] + alpha * t_W_goal,
                "q_W_goal": q_W_goal,
                "position_stiffness": command.position_stiffness,
                "position_damping": command.position_damping,
                "orientation_stiffness": command.orientation_stiffness,
                "orientation_damping": command.orientation_damping,
                "max_force": command.max_force,
                "max_torque": command.max_torque,
                "compensate_gravity": command.compensate_gravity,
            }
            self._step_once()
        self._step_for_seconds(command.settle_s)
        return {
            "object_name": name,
            "requested_goal": command.goal.model_dump(mode="json"),
            "resolved_position_w": t_W_goal[0].tolist(),
            "resolved_rotation_xyzw_w": q_W_goal[0].tolist(),
            "final_pose_w": self.base_env.arena_world.get_pose_w(name)[0].tolist(),
        }

    def _pose_goal(self, command: MoveCommand, T_W_O: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        goal = command.goal
        device = self.base_env.device
        dtype = T_W_O.dtype
        if goal.relative_to is None:
            t_W_R = torch.zeros((1, 3), device=device, dtype=dtype)
            q_W_R = torch.tensor([[0.0, 0.0, 0.0, 1.0]], device=device, dtype=dtype)
        else:
            T_W_R = self.base_env.arena_world.get_pose_w(goal.relative_to)
            t_W_R, q_W_R = T_W_R[:, :3], T_W_R[:, 3:]

        if goal.position_xyz is None:
            t_W_goal = T_W_O[:, :3].clone()
        else:
            t_R_goal = torch.tensor([goal.position_xyz], device=device, dtype=dtype)
            if goal.keep_current_xy:
                t_R_current = quat_apply_inverse(q_W_R, T_W_O[:, :3] - t_W_R)
                t_R_goal[:, :2] = t_R_current[:, :2]
            t_W_goal = t_W_R + quat_apply(q_W_R, t_R_goal)

        if goal.rotation_xyzw is None:
            existing_hold = self._pose_holds.get(command.object_name)
            q_W_goal = existing_hold["q_W_goal"] if existing_hold is not None else T_W_O[:, 3:].clone()
        else:
            q_R_goal = torch.tensor([goal.rotation_xyzw], device=device, dtype=dtype)
            q_W_goal = quat_mul(q_W_R, q_R_goal)
        return t_W_goal, q_W_goal

    def _joint_effort_to(self, command: JointEffortToCommand) -> dict[str, Any]:
        obj = self._require_articulation(command.object_name)
        assert (
            command.joint_name in obj.data.joint_names
        ), f"Unknown joint {command.joint_name!r} on {command.object_name!r}; available joints: {obj.data.joint_names}"
        joint_id = obj.data.joint_names.index(command.joint_name)
        key = (command.object_name, command.joint_name)
        if key not in self._joint_gain_defaults:
            stiffness = obj.data.joint_stiffness.torch[:, joint_id : joint_id + 1].clone()
            damping = obj.data.joint_damping.torch[:, joint_id : joint_id + 1].clone()
            self._joint_gain_defaults[key] = (stiffness, damping)
            obj.write_joint_stiffness_to_sim_index(torch.zeros_like(stiffness), joint_ids=[joint_id])
            obj.write_joint_damping_to_sim_index(torch.zeros_like(damping), joint_ids=[joint_id])
        start = float(obj.data.joint_pos.torch[0, joint_id].item())
        control_steps = max(1, round(command.duration_s / self.step_dt))
        for index in range(control_steps):
            alpha = (index + 1) / control_steps
            self._joint_holds[(command.object_name, command.joint_name)] = {
                "goal": start + alpha * (command.position - start),
                "stiffness": command.stiffness,
                "damping": command.damping,
                "effort_limit": command.effort_limit,
            }
            self._step_once()
        self._step_for_seconds(command.settle_s)
        return {
            "object_name": command.object_name,
            "joint_name": command.joint_name,
            "requested_position": command.position,
            "final_position": float(obj.data.joint_pos.torch[0, joint_id].item()),
        }

    def _step_for_seconds(self, duration_s: float) -> None:
        for _ in range(round(duration_s / self.step_dt)):
            self._step_once()

    def _step_once(self) -> None:
        assert self.steps < self.max_steps, f"Force session exceeded its {self.max_steps}-step limit."
        self._apply_holds()
        with torch.inference_mode():
            action = self.policy.get_action(self.env, self.observation)
            self.observation, _, terminated, truncated, _ = self.env.step(action)
        self.steps += 1
        if bool((terminated | truncated).any()):
            self.release_all()
            self.policy.reset(env_ids=(terminated | truncated).nonzero().flatten())

    def _apply_holds(self) -> None:
        for name, hold in self._pose_holds.items():
            obj = self.base_env.scene[name]
            T_W_O = self.base_env.arena_world.get_pose_w(name)
            v_W = self.base_env.arena_world.get_root_linear_velocity_w(name)
            omega_W = self.base_env.arena_world.get_root_angular_velocity_w(name)
            _, error_W = compute_pose_error(
                T_W_O[:, :3],
                T_W_O[:, 3:],
                hold["t_W_goal"],
                hold["q_W_goal"],
            )
            masses = obj.data.body_mass.torch
            total_mass = masses.sum(dim=1)
            acceleration_W = (
                hold["position_stiffness"] * (hold["t_W_goal"] - T_W_O[:, :3]) - hold["position_damping"] * v_W
            )
            if hold["compensate_gravity"]:
                acceleration_W[:, 2] += 9.81
            force_W = (total_mass[:, None] * acceleration_W).clamp(
                -hold["max_force"],
                hold["max_force"],
            )
            q_W_B = T_W_O[:, 3:]
            acceleration_B = quat_apply_inverse(
                q_W_B,
                hold["orientation_stiffness"] * error_W - hold["orientation_damping"] * omega_W,
            )
            inertia_B = obj.data.body_inertia.torch.reshape(self.base_env.num_envs, -1, 3, 3).sum(dim=1)
            torque_B = torch.bmm(inertia_B, acceleration_B[:, :, None]).squeeze(-1)
            torque_W = quat_apply(q_W_B, torque_B).clamp(-hold["max_torque"], hold["max_torque"])
            forces_W = masses[:, :, None] / total_mass[:, None, None] * force_W[:, None, :]
            torques_W = torch.zeros_like(forces_W)
            torques_W[:, 0, :] = torque_W
            obj.permanent_wrench_composer.set_forces_and_torques_index(
                forces=forces_W,
                torques=torques_W,
                is_global=True,
            )
            self._last_wrenches[name] = {
                "position_goal_w": hold["t_W_goal"][0].tolist(),
                "force_w": force_W[0].tolist(),
                "torque_w": torque_W[0].tolist(),
                "linear_velocity_w": v_W[0].tolist(),
            }

        for (name, joint_name), hold in self._joint_holds.items():
            obj = self.base_env.scene[name]
            joint_id = obj.data.joint_names.index(joint_name)
            position = obj.data.joint_pos.torch[:, joint_id]
            velocity = obj.data.joint_vel.torch[:, joint_id]
            effort = (hold["stiffness"] * (hold["goal"] - position) - hold["damping"] * velocity).clamp(
                -hold["effort_limit"], hold["effort_limit"]
            )
            obj.set_joint_effort_target(effort[:, None], joint_ids=[joint_id])

    def release(self, object_name: str) -> None:
        """Release all pose and joint holds associated with one scene object."""
        if object_name in self._pose_holds:
            self._pose_holds.pop(object_name)
            self.base_env.scene[object_name].permanent_wrench_composer.reset()
        for key in [key for key in self._joint_holds if key[0] == object_name]:
            self._joint_holds.pop(key)
            obj = self.base_env.scene.articulations[key[0]]
            joint_id = obj.data.joint_names.index(key[1])
            stiffness, damping = self._joint_gain_defaults.pop(key)
            obj.write_joint_stiffness_to_sim_index(stiffness, joint_ids=[joint_id])
            obj.write_joint_damping_to_sim_index(damping, joint_ids=[joint_id])

    def release_all(self) -> None:
        """Release all pose and joint holds."""
        for name in list(self._pose_holds):
            self.release(name)
        for name in sorted({key[0] for key in self._joint_holds}):
            self.release(name)

    def inspect(self, object_names: list[str] | None = None) -> dict[str, Any]:
        """Return a read-only snapshot without evaluating task predicates again."""
        if object_names is None:
            object_names = sorted((*self.base_env.scene.articulations, *self.base_env.scene.rigid_objects))
        objects = {}
        for name in object_names:
            assert name in self._scene_object_names(), f"Unknown scene object: {name!r}"
            obj = self.base_env.scene[name]
            record: dict[str, Any] = {
                "pose_w": self.base_env.arena_world.get_pose_w(name)[0].tolist(),
                "linear_velocity_w": self.base_env.arena_world.get_root_linear_velocity_w(name)[0].tolist(),
                "angular_velocity_w": self.base_env.arena_world.get_root_angular_velocity_w(name)[0].tolist(),
            }
            if name in self.base_env.scene.articulations:
                record["joints"] = dict(zip(obj.data.joint_names, obj.data.joint_pos.torch[0].tolist()))
            objects[name] = record

        progress = None
        if hasattr(self.base_env, "progress_tracker"):
            tracker = self.base_env.progress_tracker
            progress = {
                "state": dataclasses.asdict(tracker.get_state()[0]),
                "diagnostics": tracker.get_diagnostics(0),
                "events": [dataclasses.asdict(event) for event in tracker.get_events()[0]],
                "consecutive_steps": tracker.get_consecutive_step_summary(0),
            }
            with contextlib.suppress(AssertionError):
                progress["subtask_completion"] = tracker.get_subtask_completion()[0].tolist()
        return {
            "step": self.steps,
            "simulation_time_s": self.steps * self.step_dt,
            "objects": objects,
            "progress": progress,
            "active_pose_holds": sorted(self._pose_holds),
            "active_joint_holds": [list(key) for key in sorted(self._joint_holds)],
            "last_wrenches": self._last_wrenches,
        }

    def _assert_condition(self, command: AssertCommand) -> dict[str, Any]:
        if command.condition != "task_success":
            assert command.subtask_index is not None, f"{command.condition} requires subtask_index."
        deadline_steps = round(command.timeout_s / self.step_dt)
        for attempt in range(deadline_steps + 1):
            if self._condition_met(command):
                return {"condition": command.condition, "subtask_index": command.subtask_index}
            if attempt < deadline_steps:
                self._step_once()
        snapshot = self.inspect([])
        raise AssertionError(
            f"Condition {command.condition!r} was not met after {command.timeout_s:.3f}s: {snapshot['progress']}"
        )

    def _condition_met(self, command: AssertCommand) -> bool:
        tracker = self.base_env.progress_tracker
        if command.condition == "task_success":
            return bool(tracker.is_complete()[0].item())
        completion = bool(tracker.get_subtask_completion()[0, command.subtask_index].item())
        return completion if command.condition == "subtask_complete" else not completion

    def _require_wrench_object(self, name: str):
        assert name in self._scene_object_names(), f"Unknown scene object: {name!r}"
        obj = self.base_env.scene[name]
        assert hasattr(obj, "permanent_wrench_composer"), f"Object {name!r} does not support external wrenches."
        return obj

    def _require_articulation(self, name: str):
        assert name in self.base_env.scene.articulations, f"Object {name!r} is not an articulation."
        return self.base_env.scene.articulations[name]

    def _scene_object_names(self) -> set[str]:
        return set(self.base_env.scene.articulations) | set(self.base_env.scene.rigid_objects)
