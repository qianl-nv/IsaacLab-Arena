# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""PhysX deformable objects sourced from Isaac Lab examples."""

from __future__ import annotations

import copy
from typing import Any

import isaaclab.sim as sim_utils
from isaaclab.sim.spawners.spawner_cfg import DeformableObjectSpawnerCfg
from isaaclab.utils.assets import ISAACLAB_NUCLEUS_DIR
from isaaclab_physx.sim.schemas import PhysxDeformableBodyPropertiesCfg
from isaaclab_physx.sim.spawners.materials import PhysxDeformableBodyMaterialCfg, PhysxSurfaceDeformableBodyMaterialCfg

from isaaclab_arena.assets.deformable_object import DeformableObject
from isaaclab_arena.assets.register import register_asset
from isaaclab_arena.utils.bounding_box import AxisAlignedBoundingBox
from isaaclab_arena.utils.pose import Pose, PosePerEnv


class LibraryDeformableObject(DeformableObject):
    """Base class for registered deformable objects."""

    name: str
    tags = ["object", "deformable", "physx"]
    spawner_cfg: DeformableObjectSpawnerCfg
    local_bounding_box: AxisAlignedBoundingBox | None = None

    def __init__(
        self,
        instance_name: str | None = None,
        prim_path: str | None = None,
        initial_pose: Pose | PosePerEnv | None = None,
        local_bounding_box: AxisAlignedBoundingBox | None = None,
        **kwargs: Any,
    ):
        super().__init__(
            name=instance_name or self.name,
            prim_path=prim_path,
            tags=self.tags,
            spawner_cfg=copy.deepcopy(self.spawner_cfg),
            initial_pose=initial_pose,
            local_bounding_box=local_bounding_box or self.local_bounding_box,
            **kwargs,
        )


@register_asset
class DeformableCube(LibraryDeformableObject):
    """PhysX deformable cube from Isaac Lab's deformables demo."""

    name = "deformable_cube"
    spawner_cfg = sim_utils.MeshCuboidCfg(
        size=(0.6, 0.6, 0.6),
        deformable_props=PhysxDeformableBodyPropertiesCfg(),
        visual_material=sim_utils.PreviewSurfaceCfg(),
        physics_material=PhysxDeformableBodyMaterialCfg(),
    )


@register_asset
class DeformableSurface(LibraryDeformableObject):
    """PhysX deformable surface from Isaac Lab's deformables demo."""

    name = "deformable_surface"
    spawner_cfg = sim_utils.MeshRectangleCfg(
        size=(1.5, 1.0),
        resolution=(21, 21),
        deformable_props=PhysxDeformableBodyPropertiesCfg(),
        visual_material=sim_utils.PreviewSurfaceCfg(),
        physics_material=PhysxSurfaceDeformableBodyMaterialCfg(),
    )


@register_asset
class DeformableTeddyBear(LibraryDeformableObject):
    """PhysX teddy bear from Isaac Lab's Franka lift environment."""

    name = "deformable_teddy_bear"
    spawner_cfg = sim_utils.UsdFileCfg(
        usd_path=f"{ISAACLAB_NUCLEUS_DIR}/Objects/Teddy_Bear/teddy_bear.usd",
        scale=(0.01, 0.01, 0.01),
        deformable_props=PhysxDeformableBodyPropertiesCfg(),
        physics_material=PhysxDeformableBodyMaterialCfg(),
    )
