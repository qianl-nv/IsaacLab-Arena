# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Validate SimReady physics topology and create typed cached USD wrappers."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from isaaclab_arena.assets.object_type import ObjectType


@dataclass(frozen=True)
class PreparedSimReadyAsset:
    """A validated SimReady wrapper and the Arena object type used to spawn it."""

    usd_path: str
    object_type: ObjectType


def prepare_simready_asset(
    asset_path: str,
    *,
    cache_key: str | None = None,
    cache_directory_name: str = "simready-assets",
    variants: Mapping[str, str] | None = None,
) -> PreparedSimReadyAsset:
    """Validate a SimReady asset and return a rigid or articulated cached wrapper."""
    from isaaclab.utils.assets import retrieve_file_path
    from pxr import Usd, UsdGeom, UsdPhysics

    resolved_asset_path = retrieve_file_path(asset_path)
    source_stage = Usd.Stage.Open(resolved_asset_path)
    assert source_stage and source_stage.GetDefaultPrim(), "asset requires a default prim"

    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, UsdGeom.GetStageMetersPerUnit(source_stage))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.GetStageUpAxis(source_stage))
    root = UsdGeom.Xform.Define(stage, "/Asset").GetPrim()
    source = stage.DefinePrim("/Asset/Source")
    source.GetReferences().AddReference(resolved_asset_path)
    stage.SetDefaultPrim(root)
    _apply_variant_selections(source, variants or {})
    assert not stage.GetCompositionErrors(), "USD has unresolved composition errors"

    object_type = _classify_simready_physics(stage, root)
    if object_type == ObjectType.ARTICULATION and not _articulation_roots(root):
        UsdPhysics.ArticulationRootAPI.Apply(root)

    cache = Path.home() / ".cache" / "isaaclab_arena" / cache_directory_name
    cache.mkdir(parents=True, exist_ok=True)
    wrapper_key = cache_key or asset_path
    wrapper = cache / f"{hashlib.sha256(wrapper_key.encode()).hexdigest()}.usda"
    assert stage.GetRootLayer().Export(str(wrapper)), f"failed to export SimReady wrapper to {wrapper}"
    return PreparedSimReadyAsset(str(wrapper), object_type)


def _apply_variant_selections(prim, variants: Mapping[str, str]) -> None:
    """Select available variants on a prim without modifying its source layer."""
    variant_sets = prim.GetVariantSets()
    for set_name, selection in variants.items():
        if set_name in variant_sets.GetNames():
            variant_set = variant_sets.GetVariantSet(set_name)
            if selection in variant_set.GetVariantNames():
                variant_set.SetVariantSelection(selection)


def _classify_simready_physics(stage, root) -> ObjectType:
    """Classify one rigid body or a compatible rigid-body articulation tree."""
    from pxr import Usd, UsdPhysics

    prims = list(Usd.PrimRange(root, Usd.TraverseInstanceProxies()))
    bodies = [prim for prim in prims if prim.HasAPI(UsdPhysics.RigidBodyAPI)]
    assert bodies, "asset has no rigid body"
    disabled_bodies = [
        str(prim.GetPath())
        for prim in bodies
        if not bool(UsdPhysics.RigidBodyAPI(prim).GetRigidBodyEnabledAttr().Get())
    ]
    assert not disabled_bodies, f"asset has disabled rigid bodies: {disabled_bodies}"

    roots = _articulation_roots(root)
    assert len(roots) <= 1, f"asset has {len(roots)} articulation roots"
    if len(bodies) == 1:
        assert not roots, "single-rigid-body asset has an articulation root"
        return ObjectType.RIGID

    body_paths = {str(prim.GetPath()) for prim in bodies}
    edges = []
    for prim in prims:
        if not prim.IsA(UsdPhysics.Joint):
            continue
        joint = UsdPhysics.Joint(prim)
        if not bool(joint.GetJointEnabledAttr().Get()):
            continue
        body_0 = _joint_body_owner(stage, joint.GetBody0Rel(), body_paths)
        body_1 = _joint_body_owner(stage, joint.GetBody1Rel(), body_paths)
        assert (
            body_0 is not None and body_1 is not None
        ), f"joint {prim.GetPath()} must connect exactly two in-asset rigid bodies"
        assert body_0 != body_1, f"joint {prim.GetPath()} connects a rigid body to itself"
        edges.append((body_0, body_1, str(prim.GetPath())))

    assert (
        len(edges) == len(bodies) - 1
    ), f"multi-rigid-body asset requires an acyclic joint tree: found {len(bodies)} bodies and {len(edges)} joints"
    neighbors: dict[str, set[str]] = defaultdict(set)
    for body_0, body_1, joint_path in edges:
        assert body_1 not in neighbors[body_0], f"multiple joints connect the same bodies at {joint_path}"
        neighbors[body_0].add(body_1)
        neighbors[body_1].add(body_0)
    visited = set()
    pending = [next(iter(body_paths))]
    while pending:
        body_path = pending.pop()
        if body_path in visited:
            continue
        visited.add(body_path)
        pending.extend(neighbors[body_path] - visited)
    assert visited == body_paths, f"rigid-body joint graph is disconnected; unreachable bodies: {body_paths - visited}"

    if roots:
        articulation_root_path = roots[0].GetPath()
        assert all(
            prim.GetPath().HasPrefix(articulation_root_path) for prim in bodies
        ), f"articulation root {articulation_root_path} does not contain every rigid body"
    return ObjectType.ARTICULATION


def _articulation_roots(root) -> list:
    """Return articulation roots beneath root, including instance proxies."""
    from pxr import Usd, UsdPhysics

    return [
        prim
        for prim in Usd.PrimRange(root, Usd.TraverseInstanceProxies())
        if prim.HasAPI(UsdPhysics.ArticulationRootAPI)
    ]


def _joint_body_owner(stage, relationship, body_paths: set[str]) -> str | None:
    """Resolve one joint relationship target to its nearest rigid-body ancestor."""
    targets = relationship.GetTargets() if relationship else []
    if len(targets) != 1:
        return None
    prim = stage.GetPrimAtPath(targets[0])
    while prim and not prim.IsPseudoRoot():
        prim_path = str(prim.GetPath())
        if prim_path in body_paths:
            return prim_path
        prim = prim.GetParent()
    return None
