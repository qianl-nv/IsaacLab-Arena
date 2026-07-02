# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Multi-agent orchestrator for env-generation prompt parsing."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from isaaclab_arena.agentic_environment_generation.agents.prompt_normalization_agent import (
    NormalizedPrompt,
    PromptNormalizationAgent,
)
from isaaclab_arena.agentic_environment_generation.agents.relations_inference_agent import RelationsInferenceAgent
from isaaclab_arena.agentic_environment_generation.agents.tasks_inference_agent import TasksInferenceAgent
from isaaclab_arena.agentic_environment_generation.asset_matcher import match_normalized_prompt
from isaaclab_arena.agentic_environment_generation.catalogues import (
    AssetCatalogue,
    RelationCatalogue,
    TaskCatalogue,
    build_asset_catalogue,
    build_relation_catalogue,
    build_task_catalogue,
)
from isaaclab_arena.agentic_environment_generation.intent_compiler import IntentCompiler
from isaaclab_arena.agentic_environment_generation.task_validation import validate_agent_tasks
from isaaclab_arena.assets.registries import AssetRegistry
from isaaclab_arena.environments.arena_env_graph_spec import ArenaEnvInitialGraphSpec


@dataclass
class GenerationTrace:
    """Debug transcript for each pipeline stage."""

    normalized_prompt: NormalizedPrompt | None = None
    asset_match_trace: list[Any] = field(default_factory=list)
    compile_trace: list[Any] = field(default_factory=list)
    has_resolution_errors: bool = False
    raw_responses: dict[str, str] = field(default_factory=dict)


class EnvironmentGenerationAgent:
    """Parse a natural-language env-generation prompt into an ArenaEnvInitialGraphSpec."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        *,
        registry: AssetRegistry | None = None,
    ):
        """Configure sub-agents sharing one OpenAI-compatible client.

        Args:
            api_key: API token for the inference endpoint. Falls back to ``NV_API_KEY``.
            model: Model identifier at the inference endpoint.
            base_url: OpenAI-compatible inference endpoint.
            registry: Asset registry used for deterministic asset matching.
        """
        self.registry = registry or AssetRegistry()
        llm_kwargs = {
            "api_key": api_key,
            "model": model,
            "base_url": base_url,
        }
        self._normalization_agent = PromptNormalizationAgent(**llm_kwargs, validate_connection=True)
        shared_client = self._normalization_agent.client
        self._tasks_agent = TasksInferenceAgent(
            **llm_kwargs,
            client=shared_client,
            validate_connection=False,
        )
        self._relations_agent = RelationsInferenceAgent(
            **llm_kwargs,
            client=shared_client,
            validate_connection=False,
        )
        self.model = self._normalization_agent.model
        self.api_key = self._normalization_agent.api_key
        self.client = self._normalization_agent.client

    def generate_spec(
        self,
        prompt: str,
        asset_catalog: AssetCatalogue | None = None,
        relation_catalog: RelationCatalogue | None = None,
        task_catalog: TaskCatalogue | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        max_retries: int = 3,
    ) -> tuple[ArenaEnvInitialGraphSpec, str]:
        """Run the multi-agent pipeline and return a validated ArenaEnvInitialGraphSpec.

        Args:
            prompt: Natural-language env description from the end user.
            asset_catalog: Pre-built asset vocabulary. When ``None``, built from ``AssetRegistry``.
            relation_catalog: Pre-built relation vocabulary.
            task_catalog: Pre-built task vocabulary.
            temperature: Sampling temperature forwarded to each model call.
            max_tokens: Hard cap on each response length.
            max_retries: Retries per structured-output request.

        Returns:
            A ``(ArenaEnvInitialGraphSpec, raw_response)`` tuple. ``raw_response`` is a JSON
            object with one entry per pipeline stage plus compile metadata for debugging.
        """
        asset_catalog = asset_catalog or build_asset_catalogue()
        relation_catalog = relation_catalog or build_relation_catalogue()
        task_catalog = task_catalog or build_task_catalogue()
        trace = GenerationTrace()

        normalized, normalize_raw = self._normalization_agent.normalize(
            prompt,
            asset_catalog,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        trace.normalized_prompt = normalized
        trace.raw_responses["normalize"] = normalize_raw

        match_trace: list[Any] = []
        matched = match_normalized_prompt(normalized, self.registry, match_trace)
        trace.asset_match_trace = match_trace

        tasks, tasks_raw = self._tasks_agent.infer_tasks(
            prompt,
            matched,
            task_catalog,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        trace.raw_responses["tasks"] = tasks_raw
        validate_agent_tasks(tasks)

        relations, relations_raw = self._relations_agent.infer_relations(
            prompt,
            matched,
            relation_catalog,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=max_retries,
        )
        trace.raw_responses["relations"] = relations_raw

        compiler = IntentCompiler(registry=self.registry)
        initial_graph_spec = compiler.compile(matched, tasks, relations, already_matched=True)
        compiler.trace = match_trace + compiler.trace
        trace.compile_trace = compiler.trace
        trace.has_resolution_errors = compiler.has_resolution_errors

        raw_payload = {
            **trace.raw_responses,
            "reasoning": matched.reasoning,
            "compile_trace": [asdict(event) for event in compiler.trace],
            "has_resolution_errors": compiler.has_resolution_errors,
        }
        raw = json.dumps(raw_payload, indent=2)
        return initial_graph_spec, raw
