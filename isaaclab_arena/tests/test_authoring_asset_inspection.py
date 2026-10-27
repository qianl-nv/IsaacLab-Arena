# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import tempfile
from pathlib import Path

from isaaclab_arena.tests.utils.persistent_simulation_app import run_function_with_persistent_simulation_app


def _test_inspect_usd_asset(_simulation_app) -> bool:
    from pxr import Usd, UsdGeom, UsdPhysics

    from isaaclab_arena.agentic_environment_generation.simapp.asset_inspection import inspect_usd_asset

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "rigid.usda"
        stage = Usd.Stage.CreateNew(str(path))
        root = UsdGeom.Xform.Define(stage, "/Asset")
        stage.SetDefaultPrim(root.GetPrim())
        body = UsdGeom.Xform.Define(stage, "/Asset/Body").GetPrim()
        UsdPhysics.RigidBodyAPI.Apply(body)
        UsdPhysics.MassAPI.Apply(body).GetMassAttr().Set(2.0)
        cube = UsdGeom.Cube.Define(stage, "/Asset/Body/Collider").GetPrim()
        UsdPhysics.CollisionAPI.Apply(cube)
        stage.GetRootLayer().Save()

        report = inspect_usd_asset(str(path))
        assert report["topology"]["compatible"]
        assert report["topology"]["classification"] == "rigid"
        assert report["bodies"][0]["mass_kg"] == 2.0
        assert report["colliders"][0]["rigid_body_owner"] == "/Asset/Body"
        assert report["bounds_m"] == [2.0, 2.0, 2.0]
    return True


def test_inspect_usd_asset() -> None:
    assert run_function_with_persistent_simulation_app(_test_inspect_usd_asset)
