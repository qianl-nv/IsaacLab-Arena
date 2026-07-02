# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from isaaclab_arena.agentic_environment_generation.agents.llm_agent import BaseLLMAgent


def _chat_response(content: str | None = None, finish_reason: str = "stop"):
    """Build a nested mock matching the openai chat-completion response shape."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].finish_reason = finish_reason
    resp.choices[0].message.content = content
    resp.choices[0].message.reasoning_content = None
    resp.choices[0].message.tool_calls = None
    return resp


@pytest.fixture
def stub_openai():
    """Patch ``openai.OpenAI`` so ``BaseLLMAgent()`` never hits the wire."""
    with patch("isaaclab_arena.agentic_environment_generation.agents.llm_agent.OpenAI") as mock_cls:
        client = MagicMock()
        client.chat.completions.create.return_value = _chat_response(content="OK")
        mock_cls.return_value = client
        yield mock_cls


class TestBaseLLMAgentInit:
    def test_explicit_api_key_overrides_env(self, monkeypatch, stub_openai):
        monkeypatch.setenv("NV_API_KEY", "env-key")
        agent = BaseLLMAgent(api_key="explicit-key")
        assert agent.api_key == "explicit-key"

    def test_falls_back_to_env_var(self, monkeypatch, stub_openai):
        monkeypatch.setenv("NV_API_KEY", "env-key")
        agent = BaseLLMAgent()
        assert agent.api_key == "env-key"

    def test_raises_when_no_key_anywhere(self, monkeypatch, stub_openai):
        monkeypatch.delenv("NV_API_KEY", raising=False)
        with pytest.raises(AssertionError, match="API key required"):
            BaseLLMAgent()

    def test_custom_model_and_base_url(self, stub_openai):
        agent = BaseLLMAgent(api_key="k", model="custom-model", base_url="http://localhost:8000")
        assert agent.model == "custom-model"
        stub_openai.assert_called_once_with(api_key="k", base_url="http://localhost:8000")
