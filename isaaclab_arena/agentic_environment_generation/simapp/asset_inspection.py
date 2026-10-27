# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Read-only USD physics inspection for agentic environment authoring."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def inspect_usd_asset(usd_path: str, *, variants: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Inspect authored physics and geometry without modifying the source USD."""
    from isaaclab.utils.assets import retrieve_file_path
    from pxr import Usd, UsdGeom, UsdPhysics

    resolved_path = retrieve_file_path(usd_path)
    stage = Usd.Stage.CreateInMemory()
    root = stage.DefinePrim("/Asset", "Xform")
    root.GetReferences().AddReference(resolved_path)
    stage.SetDefaultPrim(root)
    _apply_variants(root, variants or {})

    prims = list(Usd.PrimRange(root, Usd.TraverseInstanceProxies()))
    body_prims = [prim for prim in prims if prim.HasAPI(UsdPhysics.RigidBodyAPI)]
    body_paths = {str(prim.GetPath()) for prim in body_prims}
    bodies = [_inspect_body(prim, UsdPhysics) for prim in body_prims]
    joints = [_inspect_joint(stage, prim, body_paths, UsdPhysics) for prim in prims if prim.IsA(UsdPhysics.Joint)]
    collisions = [
        _inspect_collision(prim, body_paths, UsdPhysics) for prim in prims if prim.HasAPI(UsdPhysics.CollisionAPI)
    ]
    articulation_roots = [str(prim.GetPath()) for prim in prims if prim.HasAPI(UsdPhysics.ArticulationRootAPI)]

    issues = _topology_issues(bodies, joints, articulation_roots)
    bbox = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_]).ComputeWorldBound(root)
    size = bbox.ComputeAlignedRange().GetSize()
    return {
        "usd_path": usd_path,
        "resolved_path": resolved_path,
        "default_prim": str(root.GetPath()),
        "meters_per_unit": float(UsdGeom.GetStageMetersPerUnit(stage)),
        "up_axis": str(UsdGeom.GetStageUpAxis(stage)),
        "variants": dict(variants or {}),
        "composition_errors": [str(error) for error in stage.GetCompositionErrors()],
        "bounds_m": [float(size[0]), float(size[1]), float(size[2])],
        "articulation_roots": articulation_roots,
        "bodies": bodies,
        "joints": joints,
        "colliders": collisions,
        "topology": {
            "compatible": not issues,
            "classification": "rigid" if len(bodies) == 1 and not articulation_roots else "articulation",
            "issues": issues,
        },
    }


def _apply_variants(root, variants: Mapping[str, str]) -> None:
    variant_sets = root.GetVariantSets()
    for set_name, selection in variants.items():
        if set_name in variant_sets.GetNames():
            variant_set = variant_sets.GetVariantSet(set_name)
            if selection in variant_set.GetVariantNames():
                variant_set.SetVariantSelection(selection)


def _attr_value(attribute, default=None):
    value = attribute.Get() if attribute else None
    return default if value is None else value


def _inspect_body(prim, UsdPhysics) -> dict[str, Any]:
    rigid = UsdPhysics.RigidBodyAPI(prim)
    mass = UsdPhysics.MassAPI(prim)
    center = _attr_value(mass.GetCenterOfMassAttr())
    inertia = _attr_value(mass.GetDiagonalInertiaAttr())
    return {
        "path": str(prim.GetPath()),
        "enabled": bool(_attr_value(rigid.GetRigidBodyEnabledAttr(), True)),
        "kinematic": bool(_attr_value(rigid.GetKinematicEnabledAttr(), False)),
        "mass_kg": _optional_float(_attr_value(mass.GetMassAttr())),
        "density_kg_m3": _optional_float(_attr_value(mass.GetDensityAttr())),
        "center_of_mass": _optional_vector(center),
        "diagonal_inertia": _optional_vector(inertia),
    }


def _inspect_joint(stage, prim, body_paths: set[str], UsdPhysics) -> dict[str, Any]:
    joint = UsdPhysics.Joint(prim)
    body_0 = _relationship_owner(stage, joint.GetBody0Rel(), body_paths)
    body_1 = _relationship_owner(stage, joint.GetBody1Rel(), body_paths)
    report = {
        "path": str(prim.GetPath()),
        "type": prim.GetTypeName(),
        "enabled": bool(_attr_value(joint.GetJointEnabledAttr(), True)),
        "body_0": body_0,
        "body_1": body_1,
    }
    if prim.IsA(UsdPhysics.RevoluteJoint):
        typed_joint = UsdPhysics.RevoluteJoint(prim)
        report.update({
            "axis": str(_attr_value(typed_joint.GetAxisAttr())),
            "lower_limit": _optional_float(_attr_value(typed_joint.GetLowerLimitAttr())),
            "upper_limit": _optional_float(_attr_value(typed_joint.GetUpperLimitAttr())),
        })
    elif prim.IsA(UsdPhysics.PrismaticJoint):
        typed_joint = UsdPhysics.PrismaticJoint(prim)
        report.update({
            "axis": str(_attr_value(typed_joint.GetAxisAttr())),
            "lower_limit": _optional_float(_attr_value(typed_joint.GetLowerLimitAttr())),
            "upper_limit": _optional_float(_attr_value(typed_joint.GetUpperLimitAttr())),
        })
    return report


def _inspect_collision(prim, body_paths: set[str], UsdPhysics) -> dict[str, Any]:
    collision = UsdPhysics.CollisionAPI(prim)
    mesh_collision = UsdPhysics.MeshCollisionAPI(prim)
    approximation = _attr_value(mesh_collision.GetApproximationAttr())
    return {
        "path": str(prim.GetPath()),
        "type": prim.GetTypeName(),
        "enabled": bool(_attr_value(collision.GetCollisionEnabledAttr(), True)),
        "rigid_body_owner": _nearest_owner(prim, body_paths),
        "approximation": str(approximation) if approximation is not None else None,
        "geometry_provenance": "authored",
        "decoded_contact_geometry": approximation in (None, "none"),
    }


def _relationship_owner(stage, relationship, body_paths: set[str]) -> str | None:
    targets = relationship.GetTargets() if relationship else []
    if len(targets) != 1:
        return None
    return _nearest_owner(stage.GetPrimAtPath(targets[0]), body_paths)


def _nearest_owner(prim, body_paths: set[str]) -> str | None:
    while prim and not prim.IsPseudoRoot():
        path = str(prim.GetPath())
        if path in body_paths:
            return path
        prim = prim.GetParent()
    return None


def _topology_issues(
    bodies: list[dict[str, Any]],
    joints: list[dict[str, Any]],
    articulation_roots: list[str],
) -> list[str]:
    issues = []
    if not bodies:
        issues.append("asset has no rigid body")
    disabled = [body["path"] for body in bodies if not body["enabled"]]
    if disabled:
        issues.append(f"disabled rigid bodies: {disabled}")
    if len(articulation_roots) > 1:
        issues.append(f"multiple articulation roots: {articulation_roots}")
    if len(bodies) > 1:
        enabled_joints = [joint for joint in joints if joint["enabled"]]
        disconnected = [joint["path"] for joint in enabled_joints if joint["body_0"] is None or joint["body_1"] is None]
        if disconnected:
            issues.append(f"joints without two in-asset rigid bodies: {disconnected}")
        if len(enabled_joints) != len(bodies) - 1:
            issues.append(
                f"multi-body asset has {len(bodies)} bodies and {len(enabled_joints)} enabled joints; expected a tree"
            )
        neighbors = {body["path"]: set() for body in bodies}
        for joint in enabled_joints:
            body_0, body_1 = joint["body_0"], joint["body_1"]
            if body_0 in neighbors and body_1 in neighbors:
                neighbors[body_0].add(body_1)
                neighbors[body_1].add(body_0)
        if neighbors:
            pending = [next(iter(neighbors))]
            visited = set()
            while pending:
                body = pending.pop()
                if body in visited:
                    continue
                visited.add(body)
                pending.extend(neighbors[body] - visited)
            if visited != neighbors.keys():
                issues.append(f"rigid-body graph is disconnected: {sorted(neighbors.keys() - visited)}")
    return issues


def _optional_float(value) -> float | None:
    return None if value is None else float(value)


def _optional_vector(value) -> list[float] | None:
    return None if value is None else [float(component) for component in value]
