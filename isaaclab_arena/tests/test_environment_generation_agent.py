# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from isaaclab_arena.agentic_environment_generation.catalogues import AssetCatalogue, RelationCatalogue, TaskCatalogue
from isaaclab_arena.agentic_environment_generation.environment_generation_agent import EnvironmentGenerationAgent


def _chat_response(content: str | None = None, reasoning_content: str | None = None, finish_reason: str = "stop"):
    """Build a nested mock matching the openai chat-completion response shape."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].finish_reason = finish_reason
    resp.choices[0].message.content = content
    resp.choices[0].message.reasoning_content = reasoning_content
    resp.choices[0].message.tool_calls = None
    return resp


@pytest.fixture
def stub_openai():
    """Patch ``openai.OpenAI`` so ``EnvironmentGenerationAgent()`` never hits the wire."""
    with patch("isaaclab_arena.agentic_environment_generation.agents.llm_agent.OpenAI") as mock_cls:
        client = MagicMock()
        client.chat.completions.create.return_value = _chat_response(content="OK")
        mock_cls.return_value = client
        yield mock_cls


@pytest.fixture
def agent(stub_openai):
    """A constructed ``EnvironmentGenerationAgent`` with a fully mocked openai client."""
    a = EnvironmentGenerationAgent(api_key="test-key")
    a.client.chat.completions.create.side_effect = None
    a.client.chat.completions.create.reset_mock()
    return a


_NORMALIZED_PROMPT: dict = {
    "reasoning": (
        "User wants a pick-and-place: foreground object is 'avocado', "
        "target container is 'bowl', background is the kitchen table."
    ),
    "robot": {
        "name": "franka",
        "query": "franka_ik",
        "description": "Franka robot arm",
    },
    "background": {
        "name": "kitchen",
        "query": "kitchen",
        "description": "Kitchen table background",
    },
    "objects": [
        {"name": "avocado", "query": "avocado", "description": "avocado to pick"},
        {"name": "bowl", "query": "bowl", "description": "bowl destination"},
    ],
    "tasks_description": "pick up the avocado and place it in the bowl",
    "relations_description": "avocado and bowl start on the kitchen table",
}

_TASKS_PAYLOAD: dict = {
    "tasks": [{
        "kind": "PickAndPlaceTask",
        "params": {
            "pick_up_object": "avocado",
            "destination_location": "bowl",
            "background_scene": "kitchen",
        },
        "description": "pick up the avocado and place it in the bowl",
    }],
}

_RELATIONS_PAYLOAD: dict = {
    "initial_state_graph": [
        {"kind": "on", "subject": "avocado", "reference": "kitchen"},
        {"kind": "on", "subject": "bowl", "reference": "kitchen"},
    ],
}


def _pipeline_responses() -> list:
    return [
        _chat_response(content=json.dumps(_NORMALIZED_PROMPT)),
        _chat_response(content=json.dumps(_TASKS_PAYLOAD)),
        _chat_response(content=json.dumps(_RELATIONS_PAYLOAD)),
    ]


def _catalog(text: str) -> AssetCatalogue:
    catalogue = AssetCatalogue()
    catalogue.to_catalog_string = lambda: text  # type: ignore[method-assign]
    return catalogue


def _relation_catalog(text: str) -> RelationCatalogue:
    catalogue = RelationCatalogue()
    catalogue.to_catalog_string = lambda: text  # type: ignore[method-assign]
    return catalogue


def _task_catalog(text: str) -> TaskCatalogue:
    catalogue = TaskCatalogue()
    catalogue.to_catalog_string = lambda: text  # type: ignore[method-assign]
    return catalogue


class TestGenerateSpec:
    def test_builds_catalogues_from_singleton_registries_when_none(self, agent):
        agent.client.chat.completions.create.side_effect = _pipeline_responses()
        with (
            patch(
                "isaaclab_arena.agentic_environment_generation.environment_generation_agent.build_asset_catalogue",
            ) as mock_build_assets,
            patch(
                "isaaclab_arena.agentic_environment_generation.environment_generation_agent.build_relation_catalogue",
            ) as mock_build_relations,
            patch(
                "isaaclab_arena.agentic_environment_generation.environment_generation_agent.build_task_catalogue",
            ) as mock_build_tasks,
        ):
            mock_build_assets.return_value = _catalog("<<ASSET-CATALOG>>")
            mock_build_relations.return_value = _relation_catalog("<<RELATION-CATALOG>>")
            mock_build_tasks.return_value = _task_catalog("<<TASK-CATALOG>>")
            agent.generate_spec("p")
        mock_build_assets.assert_called_once_with()
        mock_build_relations.assert_called_once_with()
        mock_build_tasks.assert_called_once_with()

    def test_runs_multi_stage_pipeline(self, agent):
        agent.client.chat.completions.create.side_effect = _pipeline_responses()
        spec, raw = agent.generate_spec(
            "p",
            asset_catalog=_catalog("catalog"),
            relation_catalog=_relation_catalog("RELATIONS"),
            task_catalog=_task_catalog("TASKS"),
        )
        assert spec.tasks[0].kind == "PickAndPlaceTask"
        assert spec.env_name
        assert agent.client.chat.completions.create.call_count == 3
        parsed_raw = json.loads(raw)
        assert {"normalize", "tasks", "relations"}.issubset(set(parsed_raw))
        assert "compile_trace" in parsed_raw

    def test_structured_calls_use_json_schema(self, agent):
        agent.client.chat.completions.create.side_effect = _pipeline_responses()
        agent.generate_spec(
            "p",
            asset_catalog=_catalog("catalog"),
            relation_catalog=_relation_catalog("RELATIONS"),
            task_catalog=_task_catalog("TASKS"),
        )
        schema_names = [
            call.kwargs["response_format"]["json_schema"]["name"]
            for call in agent.client.chat.completions.create.call_args_list
            if "response_format" in call.kwargs
        ]
        assert schema_names == ["NormalizedPrompt", "TasksInferenceSpec", "RelationsInferenceSpec"]

    def test_tolerates_unescaped_control_chars(self, agent):
        payload = dict(_NORMALIZED_PROMPT)
        payload["reasoning"] = "pick up\tthe\tavocado"
        raw = json.dumps(payload).replace("\\t", "\t")
        agent.client.chat.completions.create.side_effect = [
            _chat_response(content=raw),
            _chat_response(content=json.dumps(_TASKS_PAYLOAD)),
            _chat_response(content=json.dumps(_RELATIONS_PAYLOAD)),
        ]
        spec, raw = agent.generate_spec(
            "p",
            asset_catalog=_catalog("catalog"),
            relation_catalog=_relation_catalog("RELATIONS"),
            task_catalog=_task_catalog("TASKS"),
        )
        assert "\t" in json.loads(raw)["reasoning"]

    def test_user_message_contains_catalog_and_prompt(self, agent):
        agent.client.chat.completions.create.side_effect = _pipeline_responses()
        agent.generate_spec(
            "user wants avocado on kitchen",
            asset_catalog=_catalog("<<CATALOG-MARKER>>"),
            relation_catalog=_relation_catalog("<<RELATIONS-MARKER>>"),
            task_catalog=_task_catalog("<<TASKS-MARKER>>"),
        )
        first_call_messages = agent.client.chat.completions.create.call_args_list[0].kwargs["messages"]
        assert first_call_messages[1]["content"]
        assert "<<CATALOG-MARKER>>" in first_call_messages[1]["content"]
        assert "user wants avocado on kitchen" in first_call_messages[1]["content"]

    def test_raises_when_response_has_no_choices(self, agent):
        resp = MagicMock()
        resp.choices = []
        agent.client.chat.completions.create.return_value = resp
        with pytest.raises(RuntimeError, match="failed"):
            agent.generate_spec(
                "p",
                asset_catalog=_catalog("catalog"),
                relation_catalog=_relation_catalog("RELATIONS"),
                task_catalog=_task_catalog("TASKS"),
                max_retries=1,
            )

    def test_retries_after_api_error_then_succeeds(self, agent):
        agent.client.chat.completions.create.side_effect = [
            ConnectionError("timeout"),
            *_pipeline_responses(),
        ]
        spec, _ = agent.generate_spec(
            "p",
            asset_catalog=_catalog("catalog"),
            relation_catalog=_relation_catalog("RELATIONS"),
            task_catalog=_task_catalog("TASKS"),
            max_retries=3,
        )
        assert spec.tasks[0].kind == "PickAndPlaceTask"
        assert agent.client.chat.completions.create.call_count == 4


@pytest.mark.flaky(max_runs=3, min_passes=1)
def test_generate_spec_against_live_endpoint():
    """End-to-end smoke test against the real OpenAI-compatible endpoint."""
    agent = EnvironmentGenerationAgent()
    asset_catalog = _catalog(
        "EMBODIMENTS: franka_ik\n\n"
        "BACKGROUNDS: maple_table_kitchen\n\n"
        "OBJECTS (2):\n"
        "- avocado_robolab  tags=['vegetable']\n"
        "- bowl_robolab  tags=['container']"
    )
    task_catalog = _task_catalog(
        "TASKS (1):\n- PickAndPlaceTask (pick_up_object, destination_location, background_scene): Pick-and-place task."
    )
    spec, raw = agent.generate_spec(
        "pick up the avocado and place it in the bowl on the kitchen table",
        asset_catalog=asset_catalog,
        task_catalog=task_catalog,
    )
    assert isinstance(raw, str) and raw
    meta = json.loads(raw)
    assert spec.tasks, "ArenaEnvInitialGraphSpec must contain at least one task"
    assert spec.nodes, "ArenaEnvInitialGraphSpec must contain at least one node"
    assert meta.get("reasoning"), "Pipeline reasoning must be populated"
