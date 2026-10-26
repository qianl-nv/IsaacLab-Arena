# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Registered asset definitions and construction metadata."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from inspect import getattr_static
from types import MappingProxyType
from typing import Any, Generic, TypeVar

from isaaclab_arena.assets.object_type import ObjectType

AssetT = TypeVar("AssetT")


class AssetKind(Enum):
    """Role an asset can fill in an Arena environment."""

    ASSET = "asset"
    OBJECT = "object"
    EMBODIMENT = "embodiment"
    BACKGROUND = "background"
    LIGHT = "light"


def infer_asset_kind(tags: tuple[str, ...]) -> AssetKind:
    """Infer an asset kind from legacy registry tags."""
    for tag, kind in (
        ("embodiment", AssetKind.EMBODIMENT),
        ("background", AssetKind.BACKGROUND),
        ("light", AssetKind.LIGHT),
        ("object", AssetKind.OBJECT),
    ):
        if tag in tags:
            return kind
    return AssetKind.ASSET


@dataclass(frozen=True)
class AssetDefinition(Generic[AssetT]):
    """Describe a registered asset and create runtime instances of it."""

    registry_name: str
    """Unique lookup key in ``AssetRegistry``."""

    factory: Callable[..., AssetT]
    """Runtime asset class or factory."""

    tags: tuple[str, ...] = ()
    """Catalogue tags used for discovery."""

    asset_kind: AssetKind = AssetKind.ASSET
    """Environment role produced by the factory."""

    object_type: ObjectType | None = None
    """Physics object type, or None for assets that are not scene objects."""

    default_params: Mapping[str, Any] = field(default_factory=dict)
    """Default factory arguments copied for each created asset."""

    usd_path: str | None = None
    """Convenience declaration for a definition with one root USD."""

    usd_resources: Mapping[str, str] = field(default_factory=dict)
    """Named USD resources for assets such as multi-part embodiments."""

    primary_usd_name: str | None = None
    """Name in ``usd_resources`` returned by ``resolve_usd_path``."""

    def __post_init__(self) -> None:
        assert self.registry_name, "Asset definition registry_name must not be empty"
        assert callable(self.factory), "Asset definition factory must be callable"
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "default_params", MappingProxyType(deepcopy(dict(self.default_params))))
        usd_resources = dict(self.usd_resources)
        primary_usd_name = self.primary_usd_name
        if self.usd_path is not None:
            assert (
                "root" not in usd_resources or usd_resources["root"] == self.usd_path
            ), "usd_path and usd_resources['root'] must match"
            usd_resources.setdefault("root", self.usd_path)
            primary_usd_name = primary_usd_name or "root"
        if primary_usd_name is not None:
            assert (
                primary_usd_name in usd_resources
            ), f"Primary USD {primary_usd_name!r} is not declared in usd_resources"
        object.__setattr__(self, "usd_resources", MappingProxyType(usd_resources))
        object.__setattr__(self, "primary_usd_name", primary_usd_name)

    @classmethod
    def from_factory(cls, factory: Callable[..., AssetT]) -> AssetDefinition[AssetT]:
        """Create a definition from a legacy registered class or factory."""
        registry_name = getattr(factory, "registry_name", None)
        assert registry_name, f"{factory!r} must declare registry_name"
        tags = tuple(getattr(factory, "tags", ()) or ())
        declared_kind = getattr(factory, "asset_kind", None)
        asset_kind = declared_kind if isinstance(declared_kind, AssetKind) else infer_asset_kind(tags)
        # Read statically. Descriptors such as LightwheelLazyPath perform I/O when
        # accessed through getattr and must stay lazy.
        declared_usd_path = getattr_static(factory, "usd_path", None)
        usd_path = declared_usd_path if isinstance(declared_usd_path, str) else None
        return cls(
            registry_name=registry_name,
            factory=factory,
            tags=tags,
            asset_kind=asset_kind,
            object_type=getattr(factory, "object_type", None),
            usd_path=usd_path,
        )

    def create(self, **instance_params: Any) -> AssetT:
        """Create an asset, applying instance parameters over copied defaults."""
        params = deepcopy(dict(self.default_params))
        params.update(instance_params)
        asset = self.factory(**params)
        with suppress(AttributeError):
            asset._asset_definition = self
            asset.registry_name = self.registry_name
        return asset

    def resolve_usd_path(self) -> str | None:
        """Return the statically declared root USD path, when available."""
        if self.primary_usd_name is None:
            return None
        return self.usd_resources[self.primary_usd_name]
