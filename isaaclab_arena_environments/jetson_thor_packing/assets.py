# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Attach compound rigid-body physics to the Blender MCP exports."""

from pathlib import Path

from isaaclab_arena.assets.background import Background
from isaaclab_arena.assets.object import Object
from isaaclab_arena.assets.object_type import ObjectType
from isaaclab_arena.assets.register import register_asset

ASSET_DIRECTORY = Path(__file__).resolve().parents[2] / "artifacts/jetson_thor_packing/assets"
MASSES_KG = {
    "thor_board": 1.5,
    "board_tray": 0.18,
    "ac_cable_us": 0.14,
    "ac_cable_eu": 0.14,
    "usb_cable": 0.06,
    "power_supply": 0.65,
}


def physics_asset(asset_name: str, asset_directory: str | None = None) -> str:
    """Return a USD with explicit collision panels and one rigid body per assembly."""
    from pxr import PhysxSchema, Usd, UsdGeom, UsdPhysics, UsdShade

    directory = Path(asset_directory) if asset_directory else ASSET_DIRECTORY
    source = directory / f"{asset_name}.usdc"
    assert source.is_file(), f"Missing Blender export {source}; run build_with_mcp.py first."
    target = directory / f"{asset_name}.physics.usda"
    if target.is_file() and target.stat().st_mtime > max(source.stat().st_mtime, Path(__file__).stat().st_mtime):
        return str(target)
    original = Usd.Stage.Open(str(source))
    working = target.with_suffix(".working.usda")
    original.Flatten().Export(str(working))
    stage = Usd.Stage.Open(str(working))
    root = stage.GetPrimAtPath("/Asset")
    stage.SetDefaultPrim(root)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    material = UsdShade.Material.Define(stage, "/Asset/PackingContactMaterial")
    surface = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    surface.CreateStaticFrictionAttr(0.65)
    surface.CreateDynamicFrictionAttr(0.5)
    surface.CreateRestitutionAttr(0.0)
    panels = 0
    for prim in stage.Traverse():
        is_collision = any(part.startswith("COL_") for part in str(prim.GetPath()).split("/"))
        if prim.IsA(UsdGeom.Mesh) and is_collision:
            UsdPhysics.CollisionAPI.Apply(prim)
            UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr("convexHull")
            contact = PhysxSchema.PhysxCollisionAPI.Apply(prim)
            contact.CreateContactOffsetAttr(0.0005)
            contact.CreateRestOffsetAttr(0.0)
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material, materialPurpose="physics")
            UsdGeom.Imageable(prim).CreateVisibilityAttr("invisible")
            panels += 1
    assert panels > 0, "Blender export must include the authored COL_ collision panels"
    if asset_name == "background":
        bodies = [
            stage.GetPrimAtPath("/Asset/background/" + name)
            for name in ("Table", "Carton", "OpenLid", "ACBay", "USBBay", "PowerBay")
        ]
        for body in bodies:
            assert body.IsValid(), "Missing background physics assembly"
            UsdPhysics.RigidBodyAPI.Apply(body).CreateKinematicEnabledAttr(True)
    else:
        assert asset_name in MASSES_KG
        UsdPhysics.RigidBodyAPI.Apply(root)
        UsdPhysics.MassAPI.Apply(root).CreateMassAttr(MASSES_KG[asset_name])
        rigid = PhysxSchema.PhysxRigidBodyAPI.Apply(root)
        rigid.CreateSolverPositionIterationCountAttr(16)
        rigid.CreateSolverVelocityIterationCountAttr(4)
        rigid.CreateMaxDepenetrationVelocityAttr(1.0)
    stage.GetRootLayer().Save()
    working.replace(target)
    return str(target)


@register_asset
class ThorPackingTable(Background):
    """Table and open carton with three fixed accessory receptacles."""

    registry_name = "thor_packing_table"
    tags = ["background", "packing"]

    def __init__(self, name: str = "packing_table", asset_directory: str | None = None, **kwargs):
        super().__init__(name=name, usd_path=physics_asset("background", asset_directory), object_min_z=0.5, **kwargs)


@register_asset
class ThorPackingPart(Object):
    """One rigid kit component or the removable upper cardboard tray."""

    registry_name = "thor_packing_part"
    tags = ["packing"]
    object_type = ObjectType.RIGID

    def __init__(self, asset_name: str, name: str | None = None, asset_directory: str | None = None, **kwargs):
        super().__init__(
            name=name or asset_name,
            usd_path=physics_asset(asset_name, asset_directory),
            object_type=ObjectType.RIGID,
            **kwargs,
        )
