# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Intent-spec and catalogue tests without live registry or SimulationApp.

Registry-touching catalogue and validation paths are exercised through mocks so
this module stays importable in Phase 1 before ``SimulationApp`` starts.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from isaaclab_arena.agentic_environment_generation.catalogues import build_relation_catalogue, build_task_catalogue
from isaaclab_arena.agentic_environment_generation.task_validation import (
    required_task_init_param_names,
    validate_agent_tasks,
)
from isaaclab_arena.environments.arena_env_graph_types import TaskSpec
from isaaclab_arena.relations.relations import IsAnchor, On


class _PickAndPlaceStub:
    """Minimal stand-in for ``PickAndPlaceTask`` constructor introspection."""

    agent_ready = True

    def __init__(self, pick_up_object, destination_location, background_scene):
        pass


class _OpenDoorStub:
    agent_ready = True

    def __init__(self, openable_object):
        pass


class _CloseDoorStub:
    agent_ready = True

    def __init__(self, openable_object):
        pass


class _RotateJointStub:
    agent_ready = False

    def __init__(self, revolute_joint):
        pass


def _mock_task_registry() -> MagicMock:
    registry = MagicMock()
    registry.get_all_keys.return_value = [
        "PickAndPlaceTask",
        "OpenDoorTask",
        "CloseDoorTask",
        "RotateRevoluteJointTask",
    ]
    registry.get_task_by_name.side_effect = lambda name: {
        "PickAndPlaceTask": _PickAndPlaceStub,
        "OpenDoorTask": _OpenDoorStub,
        "CloseDoorTask": _CloseDoorStub,
        "RotateRevoluteJointTask": _RotateJointStub,
    }[name]
    registry.is_registered.side_effect = lambda name: name in {
        "PickAndPlaceTask",
        "OpenDoorTask",
        "CloseDoorTask",
        "RotateRevoluteJointTask",
    }
    return registry


def _mock_relation_registry() -> MagicMock:
    registry = MagicMock()
    registry.get_all_keys.return_value = ["on", "is_anchor"]
    registry.is_registered.side_effect = lambda name: name in {"on", "is_anchor"}
    registry.get_object_relation_by_name.side_effect = lambda name: {"on": On, "is_anchor": IsAnchor}[name]
    return registry


def test_required_task_init_param_names_match_task_constructors():
    assert required_task_init_param_names(_PickAndPlaceStub) == [
        "pick_up_object",
        "destination_location",
        "background_scene",
    ]
    assert required_task_init_param_names(_OpenDoorStub) == ["openable_object"]
    assert required_task_init_param_names(_CloseDoorStub) == ["openable_object"]


@patch(
    "isaaclab_arena.agentic_environment_generation.catalogues.TaskRegistry",
    side_effect=lambda: _mock_task_registry(),
)
@patch(
    "isaaclab_arena.agentic_environment_generation.catalogues.agent_ready_task_names",
    return_value=frozenset({"PickAndPlaceTask", "OpenDoorTask", "CloseDoorTask"}),
)
def test_task_catalogue_lists_required_init_params(_mock_ready, _mock_registry):
    catalogue = build_task_catalogue()
    by_name = {entry.name: entry for entry in catalogue.tasks}
    assert by_name["PickAndPlaceTask"].required_params == [
        "pick_up_object",
        "destination_location",
        "background_scene",
    ]
    assert by_name["OpenDoorTask"].required_params == ["openable_object"]


@patch(
    "isaaclab_arena.agentic_environment_generation.catalogues.TaskRegistry",
    side_effect=lambda: _mock_task_registry(),
)
@patch(
    "isaaclab_arena.agentic_environment_generation.catalogues.agent_ready_task_names",
    return_value=frozenset({"PickAndPlaceTask", "OpenDoorTask", "CloseDoorTask"}),
)
def test_task_catalogue_lists_only_agent_ready_tasks(_mock_ready, _mock_registry):
    catalogue = build_task_catalogue()
    assert {entry.name for entry in catalogue.tasks} == {"PickAndPlaceTask", "OpenDoorTask", "CloseDoorTask"}


@patch(
    "isaaclab_arena.agentic_environment_generation.catalogues.ObjectRelationLibraryRegistry",
    side_effect=lambda: _mock_relation_registry(),
)
def test_relation_catalogue_matches_object_relation_registry(_mock_registry):
    catalogue = build_relation_catalogue()
    assert {entry.name for entry in catalogue.relations} == {"on", "is_anchor"}
    on_entry = next(entry for entry in catalogue.relations if entry.name == "on")
    assert on_entry.unary is False
    assert on_entry.summary == On.__doc__.strip().splitlines()[0]


@patch(
    "isaaclab_arena.agentic_environment_generation.task_validation.TaskRegistry",
    side_effect=lambda: _mock_task_registry(),
)
def test_validate_agent_tasks_rejects_non_string_task_param(_mock_registry):
    tasks = [
        TaskSpec(
            kind="PickAndPlaceTask",
            params={
                "pick_up_object": 42,
                "destination_location": "bowl",
                "background_scene": "kitchen",
            },
            description="pick and place",
        )
    ]
    with pytest.raises(AssertionError, match="must be a non-empty string"):
        validate_agent_tasks(tasks)


@patch(
    "isaaclab_arena.agentic_environment_generation.task_validation.TaskRegistry",
    side_effect=lambda: _mock_task_registry(),
)
def test_validate_agent_tasks_rejects_missing_task_params(_mock_registry):
    tasks = [
        TaskSpec(
            kind="PickAndPlaceTask",
            params={"pick_up_object": "cube"},
            description="pick and place",
        )
    ]
    with pytest.raises(AssertionError, match="missing required param"):
        validate_agent_tasks(tasks)


@patch(
    "isaaclab_arena.agentic_environment_generation.task_validation.TaskRegistry",
    side_effect=lambda: _mock_task_registry(),
)
def test_validate_agent_tasks_rejects_non_agent_ready_task(_mock_registry):
    tasks = [
        TaskSpec(
            kind="RotateRevoluteJointTask",
            params={"revolute_joint": "knob"},
            description="rotate a joint",
        )
    ]
    with pytest.raises(AssertionError, match="not agent-ready"):
        validate_agent_tasks(tasks)


@patch(
    "isaaclab_arena.agentic_environment_generation.task_validation.TaskRegistry",
    side_effect=lambda: _mock_task_registry(),
)
def test_validate_agent_tasks_accepts_valid_task_params(_mock_registry):
    tasks = [
        TaskSpec(
            kind="PickAndPlaceTask",
            params={
                "pick_up_object": "cube",
                "destination_location": "bowl",
                "background_scene": "kitchen",
            },
            description="pick up the cube and place it in the bowl",
        )
    ]
    validate_agent_tasks(tasks)
    assert tasks[0].params["pick_up_object"] == "cube"
