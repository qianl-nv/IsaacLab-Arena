# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable provenance records composed by Arena objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from isaaclab.sim.spawners.spawner_cfg import SpawnerCfg

from isaaclab_arena.utils.pose import Pose

if TYPE_CHECKING:
    from isaaclab_arena.assets.object import Object


@dataclass(frozen=True)
class SpawnSource:
    """USD or custom-spawner provenance for a spawned object."""

    usd_path: str | None
    spawner_cfg: SpawnerCfg | None
    scale: tuple[float, float, float] | None
    spawn_cfg_addon: dict[str, Any]
    asset_cfg_addon: dict[str, Any]

    def __post_init__(self) -> None:
        assert (self.usd_path is None) != (self.spawner_cfg is None), "Pass exactly one of usd_path or spawner_cfg"


@dataclass(frozen=True)
class ReferencedSource:
    """Resolved provenance for a prim nested in a parent object."""

    parent_asset: Object
    parent_scale: tuple[float, float, float]
    prim_path_in_parent_usd: str
    initial_pose_relative_to_parent: Pose
