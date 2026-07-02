# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Task-chain inference agent."""

from __future__ import annotations

from pydantic import BaseModel, Field

from isaaclab_arena.agentic_environment_generation.agents.agent_context import matched_assets_block
from isaaclab_arena.agentic_environment_generation.agents.agent_prompts import TASKS_INFERENCE_SYSTEM
from isaaclab_arena.agentic_environment_generation.agents.llm_agent import BaseLLMAgent
from isaaclab_arena.agentic_environment_generation.agents.prompt_normalization_agent import NormalizedPrompt
from isaaclab_arena.agentic_environment_generation.catalogues import TaskCatalogue
from isaaclab_arena.environments.arena_env_graph_types import TaskSpec


class TasksInferenceSpec(BaseModel):
    """Structured output for the tasks inference step."""

    tasks: list[TaskSpec] = Field(
        description="Sequential task chain. Return [] for static scenes with no robot action.",
    )


class TasksInferenceAgent(BaseLLMAgent):
    """Infer a sequential task chain from normalized prompt context."""

    def infer_tasks(
        self,
        user_prompt: str,
        normalized: NormalizedPrompt,
        task_catalog: TaskCatalogue,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        max_retries: int = 3,
    ) -> tuple[list[TaskSpec], str]:
        """Return validated task specs for the scene."""
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self._user_prompt(user_prompt, normalized, task_catalog)},
        ]
        parsed, raw = self.infer_structured(
            TasksInferenceSpec,
            messages,
            schema_name="TasksInferenceSpec",
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        assert isinstance(parsed, TasksInferenceSpec)
        return parsed.tasks, raw

    def _system_prompt(self) -> str:
        return TASKS_INFERENCE_SYSTEM

    @staticmethod
    def _user_prompt(
        user_prompt: str,
        normalized: NormalizedPrompt,
        task_catalog: TaskCatalogue,
    ) -> str:
        return (
            f"ORIGINAL USER PROMPT:\n{user_prompt}\n\n"
            f"NORMALIZED REASONING:\n{normalized.reasoning}\n\n"
            f"TASKS DESCRIPTION:\n{normalized.tasks_description}\n\n"
            f"{matched_assets_block(normalized)}\n\n"
            f"{task_catalog.to_catalog_string()}"
        )
