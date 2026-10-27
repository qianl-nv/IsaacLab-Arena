# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""SimReady workbench adapters; source assets stay in the user's download cache."""

from pathlib import Path

from isaaclab_arena.affordances.openable import Openable
from isaaclab_arena.affordances.pressable import Pressable
from isaaclab_arena.assets.background import Background
from isaaclab_arena.assets.object import Object
from isaaclab_arena.assets.object_type import ObjectType
from isaaclab_arena.assets.register import register_asset
from isaaclab_arena.assets.simready_central_asset_loader import _download_central_asset_package_to_cache
from isaaclab_arena.assets.simready_object_library import SimReadyUsdObject


def _source_stage(url, name):
    """Reference a pinned package into an editable, metre-based USD wrapper."""
    from pxr import Usd, UsdGeom, UsdPhysics

    path = _download_central_asset_package_to_cache(url)
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    root = UsdGeom.Xform.Define(stage, "/Asset").GetPrim()
    stage.SetDefaultPrim(root)
    source = stage.DefinePrim("/Asset/" + name)
    source.GetReferences().AddReference(path)
    for key, value in {"Physics": "physics", "PhysX": "Enabled"}.items():
        variants = source.GetVariantSets().GetVariantSet(key)
        if variants and value in variants.GetVariantNames():
            variants.SetVariantSelection(value)
    for prim in Usd.PrimRange(source):
        if prim.IsA(UsdPhysics.Scene):
            prim.SetActive(False)
        if prim.IsInstance():
            prim.SetInstanceable(False)
        if prim.HasAPI(UsdPhysics.ArticulationRootAPI):
            prim.RemoveAPI(UsdPhysics.ArticulationRootAPI)
    return stage, source


def _save(stage, filename):
    cache = Path.home() / ".cache/isaaclab_arena/workbench_cleanup"
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / filename
    stage.GetRootLayer().Export(str(path))
    return str(path)


def _fix_base(stage, root, body):
    from pxr import UsdPhysics

    UsdPhysics.ArticulationRootAPI.Apply(root)
    joint = UsdPhysics.FixedJoint.Define(stage, str(root.GetPath()) + "/FixedBase")
    joint.CreateBody1Rel().SetTargets([body])


def _support(stage, name, t_P, size, visible=False, kinematic=True):
    """Add a collision panel at t_P in its parent frame P."""
    from pxr import Gf, PhysxSchema, Sdf, UsdGeom, UsdPhysics, UsdShade

    body = UsdGeom.Xform.Define(stage, "/Asset/" + name)
    body.AddTranslateOp().Set(Gf.Vec3d(*t_P))
    if kinematic:
        UsdPhysics.RigidBodyAPI.Apply(body.GetPrim()).CreateKinematicEnabledAttr(True)
    cube = UsdGeom.Cube.Define(stage, str(body.GetPath()) + "/Surface")
    cube.CreateSizeAttr(1.0)
    cube.AddScaleOp().Set(Gf.Vec3f(*size))
    cube.CreateDisplayColorAttr([(0.08, 0.12, 0.18)])
    UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
    contact = PhysxSchema.PhysxCollisionAPI.Apply(cube.GetPrim())
    contact.CreateContactOffsetAttr(0.001)
    contact.CreateRestOffsetAttr(0.0)
    if not visible:
        material = UsdShade.Material.Define(stage, "/Asset/InvisibleSupport")
        shader = UsdShade.Shader.Define(stage, "/Asset/InvisibleSupport/Shader")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(0.0)
        shader.CreateInput("opacityThreshold", Sdf.ValueTypeNames.Float).Set(0.5)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(material)
    return body


@register_asset
class CleanupWorkbench(Background):
    """Blue SimReady bench with working drawers and explicit placement supports."""

    registry_name = "cleanup_workbench"
    tags = ["background", "sim-ready"]

    def __init__(self, usd_path: str, **kwargs):
        stage, source = _source_stage(usd_path, "Bench")
        from pxr import Usd, UsdPhysics

        for prim in Usd.PrimRange(source):
            if prim.IsA(UsdPhysics.PrismaticJoint):
                joint = UsdPhysics.PrismaticJoint(prim)
                if abs(joint.GetLowerLimitAttr().Get()) < 1e-6:
                    joint.GetLowerLimitAttr().Set(0.0)
            if prim.HasAPI(UsdPhysics.CollisionAPI) and any(
                body in str(prim.GetPath()) for body in ("table_01_obj_00", "drawersA_01_obj_01")
            ):
                # Its source SDF encloses empty workspace; whole-mesh convex decomposition
                # bridges the same openings. Use compound panels for this static frame.
                UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Set(False)
        _fix_base(stage, source, "/Asset/Bench/Geometry/table_01_obj_00")
        drawer = "Bench/Geometry/drawersA_01_obj_01/Collision"
        for name, t_P, size in [
            ("Bottom", (-0.155, 0, -0.026), (0.31, 0.326, 0.005)),
            ("Front", (-0.003, 0, 0.012), (0.006, 0.343, 0.084)),
            ("Back", (-0.312, 0, 0), (0.006, 0.343, 0.06)),
            ("Left", (-0.155, -0.168, 0), (0.31, 0.006, 0.06)),
            ("Right", (-0.155, 0.168, 0), (0.31, 0.006, 0.06)),
        ]:
            _support(stage, drawer + name, t_P, size, kinematic=False)
        # These thin support regions identify the real tabletop and add an upper bin shelf.
        _support(stage, "Tabletop", (0.0, 0.0, 0.668), (0.50, 1.48, 0.002))
        _support(stage, "ClutterArea", (0.0, -0.07, 0.6685), (0.44, 0.34, 0.001))
        _support(stage, "TopRack", (-0.08, 0.34, 1.20), (0.34, 0.30, 0.006))
        panels = [
            ("Pegboard", (-0.245, 0, 0.93), (0.012, 1.48, 0.52)),
            ("Floor", (0, 0, -0.015), (3, 3, 0.03)),
        ]
        for side, y in [("Left", -0.524), ("Right", 0.524)]:
            panels.extend([
                (side + "Back", (-0.245, y, 0.39), (0.015, 0.40, 0.50)),
                (side + "Bottom", (0, y, 0.14), (0.49, 0.40, 0.012)),
                (side + "Outer", (0, y - 0.20, 0.39), (0.49, 0.015, 0.50)),
                (side + "Inner", (0, y + 0.20, 0.39), (0.49, 0.015, 0.50)),
            ])
        for index, y in enumerate((-0.565, -0.29, -0.015, 0.62)):
            panels.extend([
                (f"FixedBin{index}Bottom", (-0.08, y, 1.20), (0.32, 0.26, 0.006)),
                (f"FixedBin{index}Back", (-0.235, y, 1.29), (0.008, 0.26, 0.18)),
                (f"FixedBin{index}Left", (-0.08, y - 0.13, 1.29), (0.32, 0.006, 0.18)),
                (f"FixedBin{index}Right", (-0.08, y + 0.13, 1.29), (0.32, 0.006, 0.18)),
            ])
        for name, t_P, size in panels:
            _support(stage, "Collision" + name, t_P, size, kinematic=False)
        from pxr import UsdGeom

        lead = UsdGeom.BasisCurves.Define(stage, "/Asset/PowerLead")
        lead.CreateTypeAttr("linear")
        lead.CreateCurveVertexCountsAttr([6])
        lead.CreateWidthsAttr([0.006] * 6)
        lead.CreateDisplayColorAttr([(0.025, 0.025, 0.025)])
        lead.CreatePointsAttr([
            (-0.11, -0.50, 0.722),
            (-0.15, -0.48, 0.685),
            (-0.12, -0.56, 0.68),
            (0.0, -0.62, 0.70),
            (-0.095, -0.70, 0.87),
            (-0.145, -0.70, 0.89),
        ])
        super().__init__(name="workbench", usd_path=_save(stage, "bench.usda"), object_min_z=0.05, **kwargs)


@register_asset
class CleanupSocketSet(SimReadyUsdObject, Openable):
    """Hinged SimReady case with its socket inserts retained in their fitted tray."""

    registry_name = "cleanup_socket_set"
    tags = ["object", "sim-ready"]
    object_type = ObjectType.ARTICULATION

    def __init__(self, usd_path: str, **kwargs):
        from pxr import Gf, Usd, UsdGeom, UsdPhysics

        stage, source = _source_stage(usd_path, "Case")
        base = stage.GetPrimAtPath("/Asset/Case/Geometry/Case_base")
        # The source is a disconnected collection of 20 bodies. Retain the lid articulation,
        # and attach the fitted tools to the case for a portable complete socket set.
        for prim in list(Usd.PrimRange(source)):
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Set(False)
            if prim.IsA(UsdPhysics.Joint) and prim.GetName() != "case_lid":
                prim.SetActive(False)
            if prim.HasAPI(UsdPhysics.RigidBodyAPI) and prim not in (
                base,
                stage.GetPrimAtPath("/Asset/Case/Geometry/Case_base/Case_lid"),
            ):
                prim.RemoveAPI(UsdPhysics.RigidBodyAPI)
                prim.RemoveAPI(UsdPhysics.MassAPI)
        # Retained meshes outside Case_base become fixed articulation links.
        for prim in stage.GetPrimAtPath("/Asset/Case/Geometry").GetChildren():
            if prim == base:
                continue
            UsdPhysics.RigidBodyAPI.Apply(prim)
            joint = UsdPhysics.FixedJoint.Define(stage, "/Asset/Case/Retain_" + prim.GetName())
            joint.CreateBody0Rel().SetTargets([base.GetPath()])
            joint.CreateBody1Rel().SetTargets([prim.GetPath()])
            T_W_B = UsdGeom.Xformable(base).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            T_W_L = UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            T_B_L = T_W_L * T_W_B.GetInverse()
            joint.CreateLocalPos0Attr(Gf.Vec3f(*T_B_L.ExtractTranslation()))
            joint.CreateLocalRot0Attr(Gf.Quatf(T_B_L.ExtractRotationQuat()))
        UsdPhysics.ArticulationRootAPI.Apply(source)
        _support(stage, "Case/Geometry/Case_base/CollisionBase", (0, 0, 0.014), (0.30, 0.14, 0.028), kinematic=False)
        _support(
            stage,
            "Case/Geometry/Case_base/Case_lid/CollisionLid",
            (0, 0, 0.043),
            (0.30, 0.14, 0.028),
            kinematic=False,
        )
        super().__init__(
            usd_path=_save(stage, "socket_set.usda"),
            object_type=self.object_type,
            openable_joint_name="case_lid",
            **kwargs,
        )
        self.object_cfg.init_state.joint_pos = {"case_lid": 1.65}

    def get_contact_sensor_prim_path(self):
        """Observe the case base while leaving its lid articulated."""
        return self.prim_path + "/Case/Geometry/Case_base"


@register_asset
class CleanupOscilloscope(SimReadyUsdObject, Pressable):
    """SimReady oscilloscope with its lower-left power button exposed."""

    registry_name = "cleanup_oscilloscope"
    tags = ["object", "sim-ready"]
    object_type = ObjectType.ARTICULATION

    def __init__(self, usd_path: str, **kwargs):
        from pxr import Usd, UsdPhysics

        stage, source = _source_stage(usd_path, "Scope")
        UsdPhysics.ArticulationRootAPI.Apply(source)
        for prim in Usd.PrimRange(source):
            if prim.GetName() == "joint_button_01_joint_00":
                drive = UsdPhysics.DriveAPI.Apply(prim, "linear")
                drive.CreateStiffnessAttr(0.0)
                drive.CreateDampingAttr(0.015)
        super().__init__(
            usd_path=_save(stage, "oscilloscope.usda"),
            object_type=self.object_type,
            pressable_joint_name="joint_button_01_joint_00",
            **kwargs,
        )


@register_asset
class CleanupTool(SimReadyUsdObject):
    """SimReady hand tool with damping for repeatable clutter settling."""

    registry_name = "cleanup_tool"

    def __init__(self, usd_path: str, **kwargs):
        from isaaclab.sim import RigidBodyPropertiesCfg
        from pxr import PhysxSchema, Usd, UsdPhysics

        stage, source = _source_stage(usd_path, "Tool")
        for prim in Usd.PrimRange(source):
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr("convexHull")
                contact = PhysxSchema.PhysxCollisionAPI.Apply(prim)
                contact.CreateContactOffsetAttr(0.001)
                contact.CreateRestOffsetAttr(0.0)
        super().__init__(
            usd_path=_save(stage, "tool_" + Path(usd_path).stem + ".usda"),
            spawn_cfg_addon={"rigid_props": RigidBodyPropertiesCfg(linear_damping=2.0, angular_damping=2.0)},
            **kwargs,
        )
        from isaaclab_arena.utils.usd.helpers import extract_trimesh_from_prim

        body = next(prim for prim in Usd.PrimRange(source) if prim.HasAPI(UsdPhysics.RigidBodyAPI))
        mesh = extract_trimesh_from_prim(stage, str(body.GetPath()), scale=self.scale)
        self.hull_vertices_O = mesh.convex_hull.vertices.copy()
        """Convex hull vertices in the tool's rigid-body frame O, including its spawn scale."""


@register_asset
class CleanupPowerPlug(Object):
    """Small physical plug adapter for the SimReady outlet; the lead is rendered separately."""

    registry_name = "cleanup_power_plug"
    tags = ["object"]
    object_type = ObjectType.RIGID

    def __init__(self, **kwargs):
        from isaaclab.sim import RigidBodyPropertiesCfg
        from pxr import Gf, Usd, UsdGeom, UsdPhysics

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageMetersPerUnit(stage, 1.0)
        UsdGeom.SetStageUpAxis(stage, "Z")
        body = UsdGeom.Xform.Define(stage, "/Plug")
        stage.SetDefaultPrim(body.GetPrim())
        UsdPhysics.RigidBodyAPI.Apply(body.GetPrim())
        UsdPhysics.MassAPI.Apply(body.GetPrim()).CreateMassAttr(0.03)
        for name, t_P, size, color in [
            ("Grip", (0, 0, 0), (0.035, 0.032, 0.025), (0.035, 0.035, 0.035)),
            ("PinL", (-0.025, -0.009, 0), (0.025, 0.004, 0.005), (0.6, 0.6, 0.6)),
            ("PinR", (-0.025, 0.009, 0), (0.025, 0.004, 0.005), (0.6, 0.6, 0.6)),
        ]:
            cube = UsdGeom.Cube.Define(stage, "/Plug/" + name)
            cube.CreateSizeAttr(1.0)
            cube.AddTranslateOp().Set(Gf.Vec3d(*t_P))
            cube.AddScaleOp().Set(Gf.Vec3f(*size))
            cube.CreateDisplayColorAttr([color])
            if name == "Grip":
                UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        super().__init__(
            name=self.registry_name,
            usd_path=_save(stage, "plug.usda"),
            object_type=self.object_type,
            spawn_cfg_addon={"rigid_props": RigidBodyPropertiesCfg(disable_gravity=True, linear_damping=4.0)},
            **kwargs,
        )


@register_asset
class CleanupOutlet(SimReadyUsdObject):
    """Fixed SimReady outlet with its protective cap open."""

    registry_name = "cleanup_outlet"
    tags = ["object", "sim-ready"]
    object_type = ObjectType.ARTICULATION

    def __init__(self, usd_path: str, **kwargs):
        stage, source = _source_stage(usd_path, "Outlet")
        from pxr import Usd, UsdPhysics

        for prim in Usd.PrimRange(source):
            if prim.IsA(UsdPhysics.RevoluteJoint):
                drive = UsdPhysics.DriveAPI.Apply(prim, "angular")
                drive.CreateTargetPositionAttr(-90.0)
                drive.CreateStiffnessAttr(1.0)
                drive.CreateDampingAttr(0.1)
        _fix_base(stage, source, "/Asset/Outlet/Geometry/socket_01_obj_00")
        super().__init__(usd_path=_save(stage, "outlet.usda"), object_type=self.object_type, **kwargs)
        self.object_cfg.init_state.joint_pos = {"joint_cap_01_joint_00": -1.57}
