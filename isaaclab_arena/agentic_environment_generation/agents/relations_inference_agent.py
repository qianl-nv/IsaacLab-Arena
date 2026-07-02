# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Initial spatial-relations inference agent."""

from __future__ import annotations

from pydantic import BaseModel, Field

from isaaclab_arena.agentic_environment_generation.agents.agent_context import matched_assets_block
from isaaclab_arena.agentic_environment_generation.agents.agent_prompts import RELATIONS_INFERENCE_SYSTEM
from isaaclab_arena.agentic_environment_generation.agents.llm_agent import BaseLLMAgent
from isaaclab_arena.agentic_environment_generation.agents.prompt_normalization_agent import NormalizedPrompt
from isaaclab_arena.agentic_environment_generation.catalogues import RelationCatalogue
from isaaclab_arena.environments.arena_env_graph_types import SpatialRelationSpec


class RelationsInferenceSpec(BaseModel):
    """Structured output for the relations inference step."""

    initial_state_graph: list[SpatialRelationSpec] = Field(
        description="Full snapshot of spatial relations in the starting state.",
    )


class RelationsInferenceAgent(BaseLLMAgent):
    """Infer initial spatial relations from normalized prompt context."""

    def infer_relations(
        self,
        user_prompt: str,
        normalized: NormalizedPrompt,
        relation_catalog: RelationCatalogue,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        max_retries: int = 3,
    ) -> tuple[list[SpatialRelationSpec], str]:
        """Return validated initial-state spatial relations."""
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self._user_prompt(user_prompt, normalized, relation_catalog)},
        ]
        parsed, raw = self.infer_structured(
            RelationsInferenceSpec,
            messages,
            schema_name="RelationsInferenceSpec",
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        assert isinstance(parsed, RelationsInferenceSpec)
        return parsed.initial_state_graph, raw

    def _system_prompt(self) -> str:
        return RELATIONS_INFERENCE_SYSTEM

    @staticmethod
    def _user_prompt(
        user_prompt: str,
        normalized: NormalizedPrompt,
        relation_catalog: RelationCatalogue,
    ) -> str:
        return (
            f"ORIGINAL USER PROMPT:\n{user_prompt}\n\n"
            f"NORMALIZED REASONING:\n{normalized.reasoning}\n\n"
            f"RELATIONS DESCRIPTION:\n{normalized.relations_description}\n\n"
            f"{matched_assets_block(normalized)}\n\n"
            f"{relation_catalog.to_catalog_string()}"
        )
