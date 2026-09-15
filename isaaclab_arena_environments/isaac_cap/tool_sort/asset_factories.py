# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Nucleus-hosted assets used by the industrial tool-sort benchmark."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import isaaclab.sim as sim_utils

from isaaclab_arena.assets.object import Object
from isaaclab_arena.assets.object_type import ObjectType
from isaaclab_arena.utils.pose import Pose

_ASSET_ROOT = "omniverse://isaac-dev.ov.nvidia.com/Projects/nvblox/isaac_arena/newton_envs/industrial_tool_sort"


def _normalize_initial_pose(
    initial_pose: Pose | Mapping[str, Sequence[float]] | None,
) -> Pose | None:
    """Normalize graph/YAML pose mappings to Arena poses."""
    if initial_pose is None or isinstance(initial_pose, Pose):
        return initial_pose
    return Pose(
        position_xyz=tuple(float(value) for value in initial_pose["position_xyz"]),
        rotation_xyzw=tuple(float(value) for value in initial_pose["rotation_xyzw"]),
    )


class _ToolSortManipuland(Object):
    """Rigid tool with placement bounds that account for authored initial rotation."""

    def get_world_bounding_box(self):
        initial_pose = self.get_initial_pose()
        if self.is_anchor and isinstance(initial_pose, Pose):
            return (
                self.get_bounding_box()
                .enclosing_after_rotation(initial_pose.rotation_xyzw)
                .translated(initial_pose.position_xyz)
            )
        return super().get_world_bounding_box()


def _make_tool(
    registry_name: str,
    instance_name: str,
    initial_pose: Pose | Mapping[str, Sequence[float]] | None,
) -> Object:
    tool = _ToolSortManipuland(
        name=instance_name,
        prim_path=f"{{ENV_REGEX_NS}}/{instance_name}",
        object_type=ObjectType.RIGID,
        usd_path=f"{_ASSET_ROOT}/{registry_name}/{registry_name}.usda",
        initial_pose=_normalize_initial_pose(initial_pose),
        tags=["object", "graspable", "industrial", "tool_sort"],
    )
    tool.disable_reset_pose()
    return tool


def make_vabar_tool_sort__hammer(
    instance_name: str = "hammer_0",
    initial_pose: Pose | Mapping[str, Sequence[float]] | None = None,
    **_ignored: Any,
) -> Object:
    """Create the hammer manipuland."""
    return _make_tool("vabar_tool_sort__hammer", instance_name, initial_pose)


def make_vabar_tool_sort__drill(
    instance_name: str = "drill_0",
    initial_pose: Pose | Mapping[str, Sequence[float]] | None = None,
    **_ignored: Any,
) -> Object:
    """Create the drill manipuland."""
    return _make_tool("vabar_tool_sort__drill", instance_name, initial_pose)


def make_vabar_tool_sort__round_nut(
    instance_name: str = "round_nut_0",
    initial_pose: Pose | Mapping[str, Sequence[float]] | None = None,
    **_ignored: Any,
) -> Object:
    """Create the round-nut manipuland."""
    return _make_tool("vabar_tool_sort__round_nut", instance_name, initial_pose)


def make_vabar_tool_sort__clamp(
    instance_name: str = "clamp_0",
    initial_pose: Pose | Mapping[str, Sequence[float]] | None = None,
    **_ignored: Any,
) -> Object:
    """Create the clamp manipuland."""
    return _make_tool("vabar_tool_sort__clamp", instance_name, initial_pose)


def make_industrial__tool_sort_bin(
    instance_name: str = "tool_sort_bin",
    side: str = "destination",
    appearance: str = "default",
    initial_pose: Pose | Mapping[str, Sequence[float]] | None = None,
    **_ignored: Any,
) -> Object:
    """Create a source or compartmented destination bin."""
    assert side in {"source", "destination"}, f"Invalid tool-sort bin side: {side!r}"
    assert appearance == "default", "Only the default bin appearance is available."
    leaf = "bin1.usda" if side == "source" else "bin2_default.usda"
    return Object(
        name=instance_name,
        prim_path=f"{{ENV_REGEX_NS}}/{instance_name}",
        object_type=ObjectType.RIGID,
        usd_path=f"{_ASSET_ROOT}/industrial__tool_sort_bin/{leaf}",
        initial_pose=_normalize_initial_pose(initial_pose),
        collision_mode="mesh",
        spawn_cfg_addon={
            "rigid_props": sim_utils.RigidBodyPropertiesCfg(kinematic_enabled=True),
        },
        tags=["object", "container", "industrial", "tool_sort"],
    )


make_vabar_tool_sort__hammer.name = "vabar_tool_sort__hammer"
make_vabar_tool_sort__drill.name = "vabar_tool_sort__drill"
make_vabar_tool_sort__round_nut.name = "vabar_tool_sort__round_nut"
make_vabar_tool_sort__clamp.name = "vabar_tool_sort__clamp"
make_industrial__tool_sort_bin.name = "industrial__tool_sort_bin"

TOOL_SORT_ASSET_ENTRY_POINTS = {
    make_vabar_tool_sort__hammer.name: make_vabar_tool_sort__hammer,
    make_vabar_tool_sort__drill.name: make_vabar_tool_sort__drill,
    make_vabar_tool_sort__round_nut.name: make_vabar_tool_sort__round_nut,
    make_vabar_tool_sort__clamp.name: make_vabar_tool_sort__clamp,
    make_industrial__tool_sort_bin.name: make_industrial__tool_sort_bin,
}
