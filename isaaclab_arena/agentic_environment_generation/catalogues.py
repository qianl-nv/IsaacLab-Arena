# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Asset, relation, and task catalogues for agent prompts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from isaaclab_arena.agentic_environment_generation.task_validation import required_task_init_param_names
from isaaclab_arena.assets.registries import AssetRegistry, ObjectRelationLibraryRegistry, TaskRegistry
from isaaclab_arena.relations.relations import RelationBase


@dataclass
class AssetCatalogue:
    """Registered asset vocabulary grouped for the agent prompt."""

    embodiments: list[str] = field(default_factory=list)
    backgrounds: list[str] = field(default_factory=list)
    objects: list[dict[str, Any]] = field(default_factory=list)

    def to_catalog_string(self) -> str:
        """Format this catalogue as the user-message vocabulary block."""
        object_lines = "\n".join(
            f"- {o['name']}  tags={o['tags']}" for o in sorted(self.objects, key=lambda o: o["name"])
        )
        return (
            f"EMBODIMENTS: {', '.join(sorted(self.embodiments))}\n\n"
            f"BACKGROUNDS: {', '.join(sorted(self.backgrounds))}\n\n"
            f"OBJECTS ({len(self.objects)}):\n{object_lines}"
        )


def build_asset_catalogue(registry: AssetRegistry | None = None) -> AssetCatalogue:
    """Collect registered embodiments, backgrounds, and pick-up objects from ``AssetRegistry``."""
    registry = registry or AssetRegistry()
    catalogue = AssetCatalogue()
    for name in registry.get_all_keys():
        cls = registry.get_asset_by_name(name)
        tags = getattr(cls, "tags", None) or []
        if "embodiment" in tags:
            catalogue.embodiments.append(name)
        elif "background" in tags:
            catalogue.backgrounds.append(name)
        elif "object" in tags:
            catalogue.objects.append({"name": name, "tags": [t for t in tags if t != "object"]})
    return catalogue


def _first_docstring_line(cls: type) -> str:
    doc = cls.__doc__ or ""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


@dataclass
class RelationCatalogueEntry:
    """One registered spatial relation exposed to the agent."""

    name: str
    unary: bool
    summary: str


@dataclass
class RelationCatalogue:
    """Registered object-relation vocabulary for the agent prompt."""

    relations: list[RelationCatalogueEntry] = field(default_factory=list)

    def to_catalog_string(self) -> str:
        """Format this catalogue as the user-message RELATIONS block."""
        lines = []
        for entry in sorted(self.relations, key=lambda r: r.name):
            arity = "unary" if entry.unary else "binary"
            lines.append(f"- {entry.name} ({arity}): {entry.summary}")
        return f"RELATIONS ({len(self.relations)}):\n" + "\n".join(lines)


def build_relation_catalogue(
    registry: ObjectRelationLibraryRegistry | None = None,
) -> RelationCatalogue:
    """Collect registered object relations from ``ObjectRelationLibraryRegistry``."""
    registry = registry or ObjectRelationLibraryRegistry()
    catalogue = RelationCatalogue()
    for name in registry.get_all_keys():
        relation_cls = registry.get_object_relation_by_name(name)
        assert issubclass(relation_cls, RelationBase), f"{name!r} is not a RelationBase subclass"
        catalogue.relations.append(
            RelationCatalogueEntry(
                name=name,
                unary=relation_cls.is_unary(),
                summary=_first_docstring_line(relation_cls),
            )
        )
    return catalogue


@dataclass
class TaskCatalogueEntry:
    """One agent_ready task exposed to the agent."""

    name: str
    required_params: list[str]
    summary: str


@dataclass
class TaskCatalogue:
    """Agent-ready task vocabulary for the agent prompt."""

    tasks: list[TaskCatalogueEntry] = field(default_factory=list)

    def to_catalog_string(self) -> str:
        """Format this catalogue as the user-message TASKS block."""
        lines = []
        for entry in sorted(self.tasks, key=lambda t: t.name):
            params = ", ".join(entry.required_params)
            lines.append(f"- {entry.name} ({params}): {entry.summary}")
        return f"TASKS ({len(self.tasks)}):\n" + "\n".join(lines)


def agent_ready_task_names(registry: TaskRegistry | None = None) -> frozenset[str]:
    """Return ``TaskRegistry`` keys for tasks marked with ``@agent_ready``."""
    registry = registry or TaskRegistry()
    return frozenset(
        name for name in registry.get_all_keys() if getattr(registry.get_task_by_name(name), "agent_ready", False)
    )


def build_task_catalogue(registry: TaskRegistry | None = None) -> TaskCatalogue:
    """Collect agent_ready tasks from ``TaskRegistry``."""
    registry = registry or TaskRegistry()
    catalogue = TaskCatalogue()
    for name in sorted(agent_ready_task_names(registry)):
        task_cls = registry.get_task_by_name(name)
        catalogue.tasks.append(
            TaskCatalogueEntry(
                name=name,
                required_params=required_task_init_param_names(task_cls),
                summary=_first_docstring_line(task_cls),
            )
        )
    return catalogue
