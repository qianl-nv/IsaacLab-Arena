# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Task validation helpers for agent-emitted task chains."""

from __future__ import annotations

import inspect

from isaaclab_arena.assets.registries import TaskRegistry
from isaaclab_arena.environments.arena_env_graph_types import TaskSpec


def required_task_init_param_names(task_cls: type) -> list[str]:
    """Get the list of required parameters from a task class constructor."""
    sig = inspect.signature(task_cls.__init__)
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name == "self":
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return required


def validate_agent_tasks(tasks: list[TaskSpec], registry: TaskRegistry | None = None) -> None:
    """Assert each task is agent-ready and carries required constructor params."""
    registry = registry or TaskRegistry()
    for task in tasks:
        task_cls = registry.get_task_by_name(task.kind)
        assert getattr(task_cls, "agent_ready", False), f"Task {task.kind!r} is not agent-ready"
        assert task.description and task.description.strip(), f"Task {task.kind!r} requires a non-empty description"
        for required_param in required_task_init_param_names(task_cls):
            assert required_param in task.params, f"Task {task.kind!r} is missing required param {required_param}"
            value = task.params[required_param]
            assert (
                isinstance(value, str) and value.strip()
            ), f"Task {task.kind!r} required param {required_param!r} must be a non-empty string"
