# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Common scene-facing contract for Arena objects."""

from __future__ import annotations

from abc import ABC, abstractmethod

from isaaclab.assets import AssetBaseCfg
from isaaclab.managers import EventTermCfg
from isaaclab.sensors.contact_sensor.contact_sensor_cfg import ContactSensorCfg

# Re-export ObjectType from the lightweight module so existing
# `from isaaclab_arena.assets.object_base import ObjectType` consumers keep working,
# while pure-Python spec modules can import from `object_type` directly without
# pulling in isaaclab/omni/pxr at module-load time.
from isaaclab_arena.assets.object_type import ObjectType
from isaaclab_arena.relations.placement_asset import PlaceableAsset

__all__ = [
    "ObjectBase",
    "ObjectType",
]


class ObjectBase(PlaceableAsset, ABC):
    """Base class for Arena scene objects."""

    def __init__(
        self,
        name: str,
        prim_path: str | None = None,
        object_type: ObjectType = ObjectType.BASE,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        self.prim_path = prim_path or f"{{ENV_REGEX_NS}}/{self.name}"
        self.object_type = object_type

    def set_prim_path(self, prim_path: str) -> None:
        self.prim_path = prim_path

    def get_prim_path(self) -> str:
        return self.prim_path

    @abstractmethod
    def get_object_cfg(self) -> tuple[str, AssetBaseCfg]:
        """Return the scene key and concrete Isaac Lab config."""

    def get_event_cfg(self) -> tuple[str, EventTermCfg | None]:
        """Return the reset event initialized and owned by ``PlaceableAsset``."""
        return self.name, self._pose_event_cfg

    def get_contact_sensor_cfg(self, contact_against_object: ObjectBase | None = None) -> ContactSensorCfg:
        """Return a contact sensor config when this object representation supports one."""
        raise NotImplementedError(f"{type(self).__name__} does not support contact sensors")
