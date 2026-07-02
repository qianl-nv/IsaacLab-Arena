# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import random

from isaaclab_arena.agentic_environment_generation.agents.prompt_normalization_agent import AssetSpec, NormalizedPrompt
from isaaclab_arena.agentic_environment_generation.asset_matcher import (
    ASSET_ERROR_STAGES,
    IntentResolutionTraceEvent,
    match_normalized_prompt,
)
from isaaclab_arena.agentic_environment_generation.default_params import INITIAL_STATE_SPEC_ID
from isaaclab_arena.assets.registries import AssetRegistry
from isaaclab_arena.environments.arena_env_graph_spec import ArenaEnvInitialGraphSpec
from isaaclab_arena.environments.arena_env_graph_types import (
    ArenaEnvGraphNodeSpec,
    ArenaEnvGraphNodeType,
    ArenaEnvGraphSpatialRelationSpec,
    ArenaEnvGraphStateSpec,
    SpatialRelationSpec,
    TaskSpec,
)


class IntentCompiler:
    """Compiles matched pipeline outputs into a validated :class:`ArenaEnvInitialGraphSpec`."""

    INTENT_ERROR_STAGES: frozenset[str] = frozenset({
        "relation.initial.unknown_subject",
        "relation.initial.unknown_reference",
        "task.unknown_param",
    })

    def __init__(self, registry: AssetRegistry | None = None) -> None:
        """Args:
        registry: Asset registry to use for catalog lookups.  Defaults to
            the global singleton :class:`AssetRegistry` when ``None``.
        """
        self.registry = registry or AssetRegistry()
        self.trace: list[IntentResolutionTraceEvent] = []

    @property
    def resolution_errors(self) -> list[IntentResolutionTraceEvent]:
        """Trace events flagged as failures of the last :meth:`compile` call."""
        error_stages = ASSET_ERROR_STAGES | self.INTENT_ERROR_STAGES
        return [e for e in self.trace if e.stage in error_stages]

    @property
    def has_resolution_errors(self) -> bool:
        """``True`` if the last :meth:`compile` call produced any error-stage trace events."""
        return bool(self.resolution_errors)

    def compile(
        self,
        normalized: NormalizedPrompt,
        tasks: list[TaskSpec],
        initial_state_graph: list[SpatialRelationSpec],
        env_name: str | None = None,
        *,
        already_matched: bool = False,
    ) -> ArenaEnvInitialGraphSpec:
        """Compile pipeline outputs into an :class:`ArenaEnvInitialGraphSpec`.

        Args:
            normalized: Prompt-normalization output with asset queries and node ids.
            tasks: Agent-emitted sequential task chain.
            initial_state_graph: Agent-emitted starting-state spatial relations.
            env_name: Override for the graph's ``env_name`` field.  When ``None``
                the name is derived as ``llm_gen_{background}_{first_task_kind}``.
            already_matched: When ``False`` (default), run deterministic asset
                matching before building nodes.

        Returns:
            An :class:`ArenaEnvInitialGraphSpec` ready for YAML round-tripping or
            further linking via :meth:`~ArenaEnvInitialGraphSpec.link`.
        """
        self.trace = []

        if not already_matched:
            normalized = match_normalized_prompt(normalized, self.registry, self.trace)

        nodes: list[ArenaEnvGraphNodeSpec] = []

        background_node = self._node_from_asset(normalized.background, ArenaEnvGraphNodeType.BACKGROUND)
        if background_node is not None:
            nodes.append(background_node)

        embodiment_node = self._node_from_asset(normalized.robot, ArenaEnvGraphNodeType.EMBODIMENT)
        if embodiment_node is not None:
            nodes.append(embodiment_node)

        query_to_instances: dict[str, list[str]] = {}
        for obj in normalized.objects:
            item_node = self._node_from_asset(obj, ArenaEnvGraphNodeType.OBJECT)
            if item_node is not None:
                nodes.append(item_node)
                query_to_instances.setdefault(obj.query, []).append(item_node.id)

        known_ids = {node.id for node in nodes}

        initial_state_spec = self._build_initial_state_spec(initial_state_graph, known_ids, query_to_instances)
        resolved_tasks = self._resolve_task_params_to_node_ids(tasks, known_ids, query_to_instances)

        return ArenaEnvInitialGraphSpec(
            env_name=env_name or self._derive_env_name(normalized, tasks),
            nodes=nodes,
            tasks=resolved_tasks,
            initial_state_spec=initial_state_spec,
        )

    @staticmethod
    def _sample_one_instance_for_query(query: str, query_to_instances: dict[str, list[str]]) -> str | None:
        """Return one instance id the ``query`` expands to (chosen at random), or ``None``.

        When the scene holds duplicates, exactly one instance is sampled so a single query resolves
        unambiguously. Returns ``None`` when the query resolves to no instances.

        Args:
            query: The agent-emitted item query (e.g. 'banana') shared by one or more instances.
            query_to_instances: Map from item query (e.g. 'banana') to the node ids it produced (e.g. 'banana_1'..'banana_5').
        """
        instances = query_to_instances.get(query)
        return random.choice(instances) if instances else None

    @staticmethod
    def _derive_env_name(normalized: NormalizedPrompt, tasks: list[TaskSpec]) -> str:
        background_key = normalized.background.registry_name or normalized.background.name
        first_kind = tasks[0].kind if tasks else "task"
        return f"llm_gen_{background_key}_{first_kind}"

    @staticmethod
    def _node_from_asset(asset: AssetSpec, node_type: ArenaEnvGraphNodeType) -> ArenaEnvGraphNodeSpec | None:
        """Build a graph node from a matched :class:`AssetSpec`, or ``None`` when unmatched."""
        if asset.registry_name is None:
            return None
        return ArenaEnvGraphNodeSpec(
            id=asset.name,
            name=asset.registry_name,
            type=node_type,
        )

    def _build_initial_state_spec(
        self, graph: list[SpatialRelationSpec], known_ids: set[str], query_to_instances: dict[str, list[str]]
    ) -> ArenaEnvGraphStateSpec:
        constraints: list[ArenaEnvGraphSpatialRelationSpec] = []
        for index, rel in enumerate(graph):
            constraint = self._build_spatial_constraint(rel, index, known_ids, query_to_instances)
            if constraint is not None:
                constraints.append(constraint)
        return ArenaEnvGraphStateSpec(
            id=INITIAL_STATE_SPEC_ID,
            is_delta=False,
            spatial_constraints=constraints,
            task_constraints=[],
        )

    def _build_spatial_constraint(
        self, rel: SpatialRelationSpec, index: int, known_ids: set[str], query_to_instances: dict[str, list[str]]
    ) -> ArenaEnvGraphSpatialRelationSpec | None:
        # rel.kind is guaranteed registered by SpatialRelationSpec._validate_kind_and_arity.
        # Resolve the subject endpoint; drop the whole constraint if it names no node.
        subject = self._resolve_relation_endpoint_to_node_id(
            rel.subject, "subject", rel.kind, known_ids, query_to_instances
        )
        if subject is None:
            return None

        # Binary relations carry a reference; unary ones leave it None. Resolve it when present
        # and, as with the subject, drop the constraint if it fails to resolve.
        reference = rel.reference
        if rel.reference is not None:
            reference = self._resolve_relation_endpoint_to_node_id(
                rel.reference, "reference", rel.kind, known_ids, query_to_instances
            )
            if reference is None:
                return None

        # Build a stable, human-readable id (reference segment omitted for unary relations).
        reference_part = f"_{reference}" if reference is not None else ""
        constraint_id = f"{INITIAL_STATE_SPEC_ID}_{index}_{rel.kind}{reference_part}_{subject}"
        self.trace.append(IntentResolutionTraceEvent("relation.initial.ok", subject, reference, note=rel.kind))
        return ArenaEnvGraphSpatialRelationSpec(
            id=constraint_id,
            kind=rel.kind,
            subject=subject,
            reference=reference,
            params=dict(rel.params),
        )

    def _resolve_reference_to_node_id(
        self,
        ref: str,
        known_ids: set[str],
        query_to_instances: dict[str, list[str]],
        resolved_stage: str,
        unknown_stage: str,
        note: str,
    ) -> str | None:
        """Resolve a reference to a node id: ``ref`` itself if known, else one sampled instance.

        Returns ``None`` when nothing matches. Traces ``resolved_stage`` on a sample and
        ``unknown_stage`` on a miss (an already-known ref is returned untraced).

        Args:
            ref: The agent-emitted reference (relation endpoint or task param value).
            known_ids: The set of resolved graph node ids.
            query_to_instances: Map from item query to the node ids it produced.
            resolved_stage: Trace stage recorded when a shared query is sampled.
            unknown_stage: Trace stage recorded on a miss.
            note: Free-form note attached to the trace event.
        """
        if ref in known_ids:
            return ref
        chosen = self._sample_one_instance_for_query(ref, query_to_instances)
        stage = unknown_stage if chosen is None else resolved_stage
        self.trace.append(IntentResolutionTraceEvent(stage, ref, chosen, note=note))
        return chosen

    def _resolve_relation_endpoint_to_node_id(
        self, ref: str, role: str, kind: str, known_ids: set[str], query_to_instances: dict[str, list[str]]
    ) -> str | None:
        """Resolve one relation endpoint (subject or reference) to a node id, tracing the outcome.

        Args:
            ref: The agent-emitted endpoint string.
            role: ``"subject"`` or ``"reference"``; selects the trace stage suffix.
            kind: The relation kind, recorded on the trace event.
            known_ids: The set of resolved graph node ids.
            query_to_instances: Map from item query to the node ids it produced.
        """
        return self._resolve_reference_to_node_id(
            ref,
            known_ids,
            query_to_instances,
            resolved_stage=f"relation.initial.resolved_{role}",
            unknown_stage=f"relation.initial.unknown_{role}",
            note=kind,
        )

    def _resolve_task_params_to_node_ids(
        self, tasks: list[TaskSpec], known_ids: set[str], query_to_instances: dict[str, list[str]]
    ) -> list[TaskSpec]:
        """Resolve object-valued task params to concrete node ids, returning new specs.

        Each string param is resolved to the node id it references, picking one
        instance at random when the query is shared by several. A param that
        resolves to no node is left unchanged and flagged with a ``task.unknown_param``
        error trace (so :attr:`has_resolution_errors` reports it).

        The input ``tasks`` are left unmodified: each task is copied with a fresh
        ``params`` dict, so a second ``compile`` of the same inputs re-samples from
        scratch instead of finding already resolved ids in ``known_ids`` and silently
        diverging.

        Args:
            tasks: Agent-emitted task specs.
            known_ids: The set of resolved graph node ids.
            query_to_instances: Map from item query to the node ids it produced.
        """
        resolved_tasks: list[TaskSpec] = []
        for task in tasks:
            self.trace.append(
                IntentResolutionTraceEvent("task.resolve", task.kind, task.kind, note=f"params={task.params}")
            )
            resolved_params = dict(task.params)
            for param_name, param_value in resolved_params.items():
                # ASSUMPTION: every string-valued task param is a node reference.
                # Downstream conversion will check against the task class signature.
                if isinstance(param_value, str):
                    chosen = self._resolve_reference_to_node_id(
                        param_value,
                        known_ids,
                        query_to_instances,
                        resolved_stage="task.resolved_param",
                        unknown_stage="task.unknown_param",
                        note=f"param={param_name}, task kind={task.kind}",
                    )
                    if chosen is not None:
                        resolved_params[param_name] = chosen
            resolved_tasks.append(task.model_copy(update={"params": resolved_params}))
        return resolved_tasks
