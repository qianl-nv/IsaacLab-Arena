# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Generic SimReady USD object registered for agent-generated environments."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from isaaclab_arena.assets.object import Object
from isaaclab_arena.assets.object_type import ObjectType
from isaaclab_arena.assets.register import register_asset
from isaaclab_arena.assets.registries import AssetRegistry
from isaaclab_arena.assets.simready_constants import (
    SIMREADY_PHYSICS_VARIANTS,
    SIMREADY_SEARCH_REGISTRY_PREFIX,
    SIMREADY_USD_OBJECT_REGISTRY_NAME,
)
from isaaclab_arena.utils.pose import Pose

_NON_IDENTIFIER_CHARACTERS = re.compile(r"[^a-z0-9]+")


@register_asset
class SimReadyUsdObject(Object):
    """Spawn a SimReady asset from an explicit USD path supplied in graph params."""

    registry_name = SIMREADY_USD_OBJECT_REGISTRY_NAME

    tags = ["sim-ready"]

    object_type = ObjectType.RIGID
    """Default type for direct construction; searched and prepared assets override it."""

    def __init__(
        self,
        usd_path: str,
        name: str | None = None,
        prim_path: str | None = None,
        initial_pose: Pose | None = None,
        scale: tuple[float, float, float] | None = None,
        object_type: ObjectType | str | None = None,
        **kwargs: Any,
    ):
        """Create an object from a SimReady USD file.

        Args:
            usd_path: USD path or URL of the SimReady asset.
            name: Name of the object in the scene. Defaults to the registry name.
            prim_path: Prim path of the object. Defaults to ``{ENV_REGEX_NS}/<name>``.
            initial_pose: Initial pose of the object.
            scale: Scale of the object. Defaults to ``(1.0, 1.0, 1.0)``.
            object_type: Prepared asset type. Auto-detected from the USD when omitted.
            **kwargs: Extra arguments passed to ``Object``.
        """
        assert "instance_name" not in kwargs, "instance_name was renamed to name; pass name= instead."
        assert usd_path, "simready_usd_object requires params.usd_path"
        if usd_path.startswith(("https://huggingface.co/datasets/", "hf://huggingface.co/datasets/")):
            from isaaclab_arena.assets.simready_central_asset_loader import download_and_wrap_central_asset

            prepared = download_and_wrap_central_asset(usd_path)
            usd_path = prepared.usd_path
            object_type = prepared.object_type
        if object_type is not None:
            object_type = ObjectType(object_type)
        spawn_cfg_addon = dict(kwargs.pop("spawn_cfg_addon", None) or {})
        spawn_cfg_addon.setdefault("variants", dict(SIMREADY_PHYSICS_VARIANTS))
        super().__init__(
            name=name or self.registry_name,
            prim_path=prim_path,
            tags=self.tags,
            usd_path=usd_path,
            object_type=object_type,
            scale=scale if scale is not None else (1.0, 1.0, 1.0),
            initial_pose=initial_pose,
            spawn_cfg_addon=spawn_cfg_addon,
            **kwargs,
        )

    def _build_reset_event(self):
        """Build a reset event that also restores articulation joints."""
        event_cfg = super()._build_reset_event()
        if event_cfg is None or self.object_type != ObjectType.ARTICULATION:
            return event_cfg
        from isaaclab_tasks.contrib.stack.mdp.franka_stack_events import randomize_object_pose

        from isaaclab_arena.terms.events import (
            randomize_articulation_pose_and_reset_joints,
            reset_articulation_pose_and_joints,
            reset_articulation_pose_per_env_and_joints,
            set_object_pose,
            set_object_pose_per_env,
        )

        if event_cfg.func is set_object_pose:
            event_cfg.func = reset_articulation_pose_and_joints
        elif event_cfg.func is set_object_pose_per_env:
            event_cfg.func = reset_articulation_pose_per_env_and_joints
        elif event_cfg.func is randomize_object_pose:
            event_cfg.func = randomize_articulation_pose_and_reset_joints
        else:
            raise AssertionError(f"unsupported articulation root reset function: {event_cfg.func}")
        return event_cfg

    def get_event_cfg(self):
        """Restore articulation joints even when no root-pose reset is configured."""
        name, event_cfg = super().get_event_cfg()
        if event_cfg is None and self.object_type == ObjectType.ARTICULATION:
            from isaaclab.managers import EventTermCfg, SceneEntityCfg

            from isaaclab_arena.terms.events import reset_articulation_joints

            event_cfg = EventTermCfg(
                func=reset_articulation_joints,
                mode="reset",
                params={"asset_cfg": SceneEntityCfg(name)},
            )
        return name, event_cfg


def simready_search_registry_name(search_phrase: str) -> str:
    """Return the catalogue name used to register the SimReady asset found for a search phrase."""
    slug = _NON_IDENTIFIER_CHARACTERS.sub("_", search_phrase.strip().lower()).strip("_")
    assert slug, f"search phrase {search_phrase!r} has no characters usable in a registry name"
    return f"{SIMREADY_SEARCH_REGISTRY_PREFIX}{slug}"


def register_searched_simready_object(
    search_phrase: str,
    usd_path: str,
    tags: Sequence[str] = (),
    object_type: ObjectType = ObjectType.RIGID,
) -> type[SimReadyUsdObject]:
    """Register a searched SimReady asset so it can be picked like any other catalogue object.

    Args:
        search_phrase: Phrase the asset was found for; it determines the catalogue name.
        usd_path: USD path or URL of the found asset.
        tags: Extra catalogue tags to expose alongside the SimReady ones.
        object_type: Arena asset type determined while validating the USD.

    Returns:
        The registered asset class.
    """
    searched_registry_name = simready_search_registry_name(search_phrase)
    registry = AssetRegistry()
    if registry.is_registered(searched_registry_name, ensure_loaded=False):
        return registry.get_asset_by_name(searched_registry_name)
    found_usd_path = usd_path
    found_object_type = object_type
    # Tagged 'object' unlike the generic asset, because this one carries its own usd_path.
    merged_tags = list(dict.fromkeys(["object", *SimReadyUsdObject.tags, *tags]))

    class SearchedSimReadyObject(SimReadyUsdObject):
        """A SimReady asset the search found for one object in a prompt."""

        registry_name = searched_registry_name
        tags = merged_tags
        object_type = found_object_type

        def __init__(self, **kwargs: Any):
            kwargs.setdefault("usd_path", found_usd_path)
            kwargs.setdefault("object_type", found_object_type)
            super().__init__(**kwargs)

    registry.register(SearchedSimReadyObject, searched_registry_name)
    return SearchedSimReadyObject
