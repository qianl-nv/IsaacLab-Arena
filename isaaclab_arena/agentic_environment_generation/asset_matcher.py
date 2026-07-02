# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches

from isaaclab_arena.agentic_environment_generation.agents.prompt_normalization_agent import AssetSpec, NormalizedPrompt
from isaaclab_arena.assets.registries import AssetRegistry


@dataclass
class IntentResolutionTraceEvent:
    """One step in the intent-resolution pipeline for debugging."""

    # Identifier for the resolution step, e.g. item.preferred_tags.substring.
    stage: str
    # The original query string that triggered this event.
    query: str
    # The registry key that was selected, or ``None`` when resolution failed.
    chosen: str | None
    # Human-readable annotation explaining why this choice was made.
    note: str = ""


ASSET_ERROR_STAGES: frozenset[str] = frozenset({
    # Required-tag pool is non-empty but no asset matched the query.
    "item.required_tags.miss",
    "background.required_tags.miss",
    "embodiment.required_tags.miss",
    # Required-tag pool is empty: the registry has no assets for this category.
    # The node is silently dropped in both cases, so both are resolution errors.
    "item.required_tags.empty_pool",
    "background.required_tags.empty_pool",
    "embodiment.required_tags.empty_pool",
})
"""Trace stage identifiers that indicate an asset-query failure."""


def match_asset(
    registry: AssetRegistry,
    asset: AssetSpec,
    trace_prefix: str,
    trace: list[IntentResolutionTraceEvent],
    required_tags: list[str] | None = None,
    preferred_tags: list[str] | None = None,
) -> AssetSpec:
    """Match ``asset.query`` to a registered asset key and return an updated :class:`AssetSpec`.

    Resolution proceeds in three stages:

    1. **Exact match** in the pool of assets that carry ``required_tags``.
    2. **Fuzzy match** (substring, then difflib) in the pool narrowed by
       ``required_tags + preferred_tags`` when ``preferred_tags`` is non-empty.
    3. **Fuzzy match** in the ``required_tags`` pool only (relaxed fallback).

    Args:
        registry: Registry to look up asset names in.
        asset: Asset description whose ``query`` field drives matching.
        trace_prefix: Prefix for trace event stages (e.g. ``"item"``,
            ``"background"``, ``"embodiment"``).
        trace: Mutable list that receives one :class:`IntentResolutionTraceEvent`
            per resolution step. Matcher events are appended to the trace in order.
        required_tags: Tags every candidate must carry (e.g. ``["object"]``).
        preferred_tags: Additional tags that narrow the first-pass pool
            (e.g. ``["default"]`` for embodiments). When ``None`` or empty,
            stage 2 is skipped and matching falls through directly to the
            required-tag pool.

    Returns:
        A copy of ``asset`` with ``registry_name`` set when a match is found.
    """
    if asset.registry_name is not None:
        return asset

    required_tags = required_tags or []
    query = asset.query
    candidates = sorted(registry.get_assets_with_all_tags(required_tags))
    # 1. Exact name match in a pool of assets with only the required tags.
    if query in candidates:
        trace.append(IntentResolutionTraceEvent(f"{trace_prefix}.exact", query, query))
        return asset.model_copy(update={"registry_name": query})

    # 2. Fuzzy matching in a pool narrowed by required + preferred tags.
    if preferred_tags:
        preferred_candidates = sorted(registry.get_assets_with_all_tags(required_tags + preferred_tags))
        chosen = _fuzzy_match(
            preferred_candidates,
            query,
            trace_prefix=f"{trace_prefix}.preferred_tags",
            trace=trace,
            note=f"tags={required_tags + preferred_tags}, pool size={len(preferred_candidates)}",
        )
        if chosen is not None:
            return asset.model_copy(update={"registry_name": chosen})

    # 3. Fuzzy matching in a pool of assets with only the required tags.
    chosen = _fuzzy_match(
        candidates,
        query,
        trace_prefix=f"{trace_prefix}.required_tags",
        trace=trace,
        note=f"tags={required_tags}, pool size={len(candidates)}",
    )
    return asset.model_copy(update={"registry_name": chosen})


def match_normalized_prompt(
    normalized: NormalizedPrompt,
    registry: AssetRegistry,
    trace: list[IntentResolutionTraceEvent],
) -> NormalizedPrompt:
    """Resolve every :class:`AssetSpec` in ``normalized`` against ``registry``."""
    return NormalizedPrompt(
        reasoning=normalized.reasoning,
        robot=match_asset(
            registry,
            normalized.robot,
            "embodiment",
            trace,
            required_tags=["embodiment"],
            preferred_tags=["default"],
        ),
        background=match_asset(
            registry,
            normalized.background,
            "background",
            trace,
            required_tags=["background"],
        ),
        objects=[
            match_asset(
                registry,
                obj,
                "item",
                trace,
                required_tags=["object"],
            )
            for obj in normalized.objects
        ],
        tasks_description=normalized.tasks_description,
        relations_description=normalized.relations_description,
    )


def _fuzzy_match(
    pool: list[str],
    query: str,
    trace_prefix: str,
    trace: list[IntentResolutionTraceEvent],
    note: str = "",
) -> str | None:
    """Match ``query`` within ``pool``: substring then difflib fuzzy."""
    if not pool:
        trace.append(IntentResolutionTraceEvent(f"{trace_prefix}.empty_pool", query, None, note=note))
        return None

    q = query.lower()
    substrs = [name for name in pool if q in name.lower()]
    if substrs:
        chosen = min(substrs, key=len)
        trace.append(IntentResolutionTraceEvent(f"{trace_prefix}.substring", query, chosen, note=note))
        return chosen

    matches = get_close_matches(query, pool, n=3, cutoff=0.5)
    if matches:
        # TODO(qianl): support object sets when there's multiple matching assets.
        chosen = matches[0]
        fuzzy_note = note
        if len(matches) > 1:
            ambiguity = f"multiple matches={matches}, taking first={chosen!r}"
            fuzzy_note = f"{note}; {ambiguity}" if note else ambiguity
        trace.append(IntentResolutionTraceEvent(f"{trace_prefix}.fuzzy", query, chosen, note=fuzzy_note))
        return chosen

    trace.append(IntentResolutionTraceEvent(f"{trace_prefix}.miss", query, None, note=note))
    return None
