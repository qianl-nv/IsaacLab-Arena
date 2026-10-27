# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Typed commands for bounded physical-force authoring sessions."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class ForceCommandBase(BaseModel):
    """Common strict fields for every force-session command."""

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1, max_length=128)


class PoseGoal(BaseModel):
    """Target pose expressed in the world frame or relative to a scene object."""

    model_config = ConfigDict(extra="forbid")

    position_xyz: tuple[float, float, float] | None = None
    rotation_xyzw: tuple[float, float, float, float] | None = None
    relative_to: str | None = Field(default=None, min_length=1, max_length=256)
    keep_current_xy: bool = False


class MoveCommand(ForceCommandBase):
    action: Literal["move"] = "move"
    object_name: str = Field(min_length=1, max_length=256)
    goal: PoseGoal
    duration_s: float = Field(default=2.0, gt=0.0, le=30.0)
    settle_s: float = Field(default=0.5, ge=0.0, le=30.0)
    position_stiffness: float = Field(default=150.0, gt=0.0, le=10_000.0)
    position_damping: float = Field(default=24.0, ge=0.0, le=1_000.0)
    orientation_stiffness: float = Field(default=100.0, gt=0.0, le=10_000.0)
    orientation_damping: float = Field(default=20.0, ge=0.0, le=1_000.0)
    max_force: float = Field(default=100.0, gt=0.0, le=10_000.0)
    max_torque: float = Field(default=5.0, gt=0.0, le=1_000.0)
    compensate_gravity: bool = True


class JointEffortToCommand(ForceCommandBase):
    action: Literal["joint_effort_to"] = "joint_effort_to"
    object_name: str = Field(min_length=1, max_length=256)
    joint_name: str = Field(min_length=1, max_length=256)
    position: float
    duration_s: float = Field(default=2.0, gt=0.0, le=30.0)
    settle_s: float = Field(default=0.5, ge=0.0, le=30.0)
    stiffness: float = Field(default=40.0, gt=0.0, le=10_000.0)
    damping: float = Field(default=6.0, ge=0.0, le=1_000.0)
    effort_limit: float = Field(default=30.0, gt=0.0, le=10_000.0)


class ReleaseCommand(ForceCommandBase):
    action: Literal["release"] = "release"
    object_name: str = Field(min_length=1, max_length=256)


class ReleaseAllCommand(ForceCommandBase):
    action: Literal["release_all"] = "release_all"


class WaitCommand(ForceCommandBase):
    action: Literal["wait"] = "wait"
    duration_s: float = Field(gt=0.0, le=30.0)


class InspectCommand(ForceCommandBase):
    action: Literal["inspect"] = "inspect"
    objects: list[str] | None = Field(default=None, max_length=256)


class AssertCommand(ForceCommandBase):
    action: Literal["assert"] = "assert"
    condition: Literal["task_success", "subtask_complete", "subtask_incomplete"]
    subtask_index: int | None = Field(default=None, ge=0, le=1024)
    timeout_s: float = Field(default=0.0, ge=0.0, le=30.0)


class FinishCommand(ForceCommandBase):
    action: Literal["finish"] = "finish"


ForceCommand = Annotated[
    MoveCommand
    | JointEffortToCommand
    | ReleaseCommand
    | ReleaseAllCommand
    | WaitCommand
    | InspectCommand
    | AssertCommand
    | FinishCommand,
    Field(discriminator="action"),
]
_FORCE_COMMAND_ADAPTER = TypeAdapter(ForceCommand)


def parse_force_command(value: dict[str, Any]) -> ForceCommand:
    """Validate one decoded force command."""
    return _FORCE_COMMAND_ADAPTER.validate_python(value)


def parse_force_commands(values: list[dict[str, Any]]) -> list[ForceCommand]:
    """Validate a bounded list of decoded force commands."""
    assert len(values) <= 1000, "A force run supports at most 1000 commands."
    return [parse_force_command(value) for value in values]
