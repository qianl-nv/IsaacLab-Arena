# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Prompt-normalization agent and its structured output schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field

from isaaclab_arena.agentic_environment_generation.agents.agent_prompts import PROMPT_NORMALIZATION_SYSTEM
from isaaclab_arena.agentic_environment_generation.agents.llm_agent import BaseLLMAgent
from isaaclab_arena.agentic_environment_generation.catalogues import AssetCatalogue


class AssetSpec(BaseModel):
    """Semantic description of one asset instance extracted from the user prompt."""

    name: str = Field(
        description=(
            "Unique node id for this instance. Brief semantic name; when several "
            "instances share a kind, add prompt distinguishers (left/right) or "
            "numeric suffixes (_1, _2)."
        ),
    )
    registry_name: str | None = Field(
        default=None,
        description="Exact registered asset name; always leave null — filled by the asset matcher.",
    )
    query: str = Field(
        description=(
            "Short registry search phrase aligned with the asset catalog. The matcher "
            "fuzzy-matches this against registered assets; do not emit the exact "
            "registered key unless it equals the intended search phrase."
        ),
    )
    description: str = Field(
        description="Relevant details from the prompt that help identify this asset.",
    )


class NormalizedPrompt(BaseModel):
    """Structured scene intent before registry matching and task/relation inference."""

    reasoning: str = Field(
        description="Step-by-step analysis of the user prompt before filling structured fields.",
    )
    robot: AssetSpec
    background: AssetSpec
    objects: list[AssetSpec] = Field(default_factory=list)
    tasks_description: str = Field(
        description=(
            "Natural-language summary of requested robot actions, or an explicit "
            "statement that the scene is static with no robot action."
        ),
    )
    relations_description: str = Field(
        description=(
            "Natural-language summary of starting placements and spatial layout "
            "(surfaces, anchors, distractors, articulated fixtures)."
        ),
    )


class PromptNormalizationAgent(BaseLLMAgent):
    """Extract a :class:`NormalizedPrompt` from natural language."""

    def normalize(
        self,
        prompt: str,
        asset_catalog: AssetCatalogue,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        max_retries: int = 3,
    ) -> tuple[NormalizedPrompt, str]:
        """Parse ``prompt`` into a :class:`NormalizedPrompt`."""
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": self._user_prompt(prompt, asset_catalog)},
        ]
        parsed, raw = self.infer_structured(
            NormalizedPrompt,
            messages,
            schema_name="NormalizedPrompt",
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        assert isinstance(parsed, NormalizedPrompt)
        return parsed, raw

    def _system_prompt(self) -> str:
        return PROMPT_NORMALIZATION_SYSTEM

    @staticmethod
    def _user_prompt(prompt: str, asset_catalog: AssetCatalogue) -> str:
        return f"{asset_catalog.to_catalog_string()}\n\nUSER PROMPT:\n{prompt}"
