# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Central search filtering and pinned asset preparation tests."""

from unittest.mock import Mock, patch

import pytest

from isaaclab_arena.agentic_environment_generation.simready_asset_search import search_simready_objects
from isaaclab_arena.agentic_environment_generation.simready_central_assets import search_central_objects
from isaaclab_arena.agentic_environment_generation.simready_search_interface import (
    SimReadySearchConfig,
    SimReadySourceKind,
)
from isaaclab_arena.assets.object_type import ObjectType
from isaaclab_arena.assets.simready_asset_preparation import PreparedSimReadyAsset
from isaaclab_arena.assets.simready_central_asset_loader import _parse_central_asset_url

MODULE = "isaaclab_arena.agentic_environment_generation.simready_central_assets"
LOADER = "isaaclab_arena.assets.simready_central_asset_loader"
PREPARER = "isaaclab_arena.assets.simready_asset_preparation"
REVISION = "a" * 40
URL = f"hf://huggingface.co/datasets/nvidia/simready-assets/resolve/{REVISION}/pallet/simready_usd/pallet.usd"


def _hit(count, path=URL):
    properties = [] if count is None else [{"name": "simready_metadata_rigid_body_count", "value_numeric": count}]
    return {"source": {"path": path, "usd_properties": properties}, "rrf_score": 0.5}


def test_central_requires_positive_body_metadata_and_skips_invalid_usd():
    response = Mock()
    response.json.return_value = {"hits": [_hit(None), _hit(0), _hit(2), _hit(1)]}
    with (
        patch(f"{MODULE}.requests.post", return_value=response) as post,
        patch(
            f"{MODULE}.download_and_wrap_central_asset",
            side_effect=[
                ValueError("disconnected"),
                PreparedSimReadyAsset("/cache/pallet.usda", ObjectType.RIGID),
            ],
        ) as prepare,
    ):
        candidates = search_central_objects("pallet", max_results=1)
    assert [candidate.usd_path for candidate in candidates] == ["/cache/pallet.usda"]
    assert candidates[0].object_type == ObjectType.RIGID
    assert prepare.call_count == 2
    assert "filter_by_properties_numeric" not in post.call_args.kwargs["json"]
    assert post.call_args.kwargs["timeout"] == 30


def test_central_failure_leaves_phrase_unmatched():
    with patch(f"{MODULE}.requests.post", side_effect=TimeoutError("offline")):
        catalogue = search_simready_objects(["pallet"], SimReadySearchConfig(sources=[SimReadySourceKind.CENTRAL]))
    assert catalogue.candidates == []
    assert catalogue.unmatched_phrases == ["pallet"]


def test_central_package_location_preserves_revision_and_folder():
    assert _parse_central_asset_url(URL) == (
        "nvidia/simready-assets",
        REVISION,
        "pallet/simready_usd/pallet.usd",
        "pallet",
    )


@pytest.mark.parametrize(
    "url",
    [
        URL.replace(REVISION, "main"),
        URL.replace("pallet/simready_usd", "../simready_usd"),
        URL.replace("pallet/simready_usd/", ""),
    ],
)
def test_central_rejects_unpinned_or_unbounded_packages(url):
    with pytest.raises(AssertionError):
        _parse_central_asset_url(url)


def _test_central_usd_validation(simulation_app):
    import tempfile
    import torch
    from pathlib import Path

    from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics

    from isaaclab_arena.assets.simready_central_asset_loader import download_and_wrap_central_asset

    def add_physics_body(stage, name: str, z: float) -> str:
        body_path = f"/Root/Geometry/{name}_obj_00"
        body = UsdGeom.Xform.Define(stage, body_path)
        body.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, z))
        UsdPhysics.RigidBodyAPI.Apply(body.GetPrim())
        cube = UsdGeom.Cube.Define(stage, f"{body_path}/{name}_mesh_00")
        cube.CreateSizeAttr(0.1)
        UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        return body_path

    def open_wrapper(path: str):
        layer = Sdf.Layer.Find(path)
        if layer is not None:
            layer.Reload()
        return Usd.Stage.Open(path)

    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        asset = folder / "pallet/simready_usd/pallet.usd"
        asset.parent.mkdir(parents=True)
        stage = Usd.Stage.CreateNew(str(asset))
        root = UsdGeom.Xform.Define(stage, "/Pallet").GetPrim()
        stage.SetDefaultPrim(root)
        body = UsdPhysics.RigidBodyAPI.Apply(root)
        body.CreateRigidBodyEnabledAttr(True)
        stage.GetRootLayer().Save()
        with (
            patch(f"{LOADER}._download_central_asset_package_to_cache", return_value=str(asset)),
            patch(f"{PREPARER}.Path.home", return_value=folder),
        ):
            prepared = download_and_wrap_central_asset(URL)
            assert prepared.object_type == ObjectType.RIGID
            wrapper_stage = open_wrapper(prepared.usd_path)
            wrapper_bodies = [
                prim for prim in Usd.PrimRange.Stage(wrapper_stage) if prim.HasAPI(UsdPhysics.RigidBodyAPI)
            ]
            assert len(wrapper_bodies) == 1
            body.GetRigidBodyEnabledAttr().Set(False)
            stage.GetRootLayer().Save()
            with pytest.raises(AssertionError, match="disabled"):
                download_and_wrap_central_asset(URL)
            body.GetRigidBodyEnabledAttr().Set(True)
            UsdPhysics.ArticulationRootAPI.Apply(root)
            stage.GetRootLayer().Save()
            with pytest.raises(AssertionError, match="single-rigid-body asset has an articulation root"):
                download_and_wrap_central_asset(URL)
            root.RemoveAPI(UsdPhysics.ArticulationRootAPI)

            stage.GetRootLayer().Clear()
            root = UsdGeom.Xform.Define(stage, "/Root").GetPrim()
            stage.SetDefaultPrim(root)
            base_path = add_physics_body(stage, "base", 0.0)
            lid_path = add_physics_body(stage, "lid", 0.1)
            joint = UsdPhysics.RevoluteJoint.Define(stage, "/Root/Joints/lid")
            joint.CreateBody0Rel().SetTargets([base_path])
            joint.CreateBody1Rel().SetTargets([lid_path])
            stage.GetRootLayer().Save()

            prepared = download_and_wrap_central_asset(URL)
            assert prepared.object_type == ObjectType.ARTICULATION
            wrapper_stage = open_wrapper(prepared.usd_path)
            assert wrapper_stage.GetDefaultPrim().HasAPI(UsdPhysics.ArticulationRootAPI)

            joint.GetPrim().SetActive(False)
            stage.GetRootLayer().Save()
            with pytest.raises(AssertionError, match="joint tree"):
                download_and_wrap_central_asset(URL)

            joint.GetPrim().SetActive(True)
            duplicate = UsdPhysics.FixedJoint.Define(stage, "/Root/Joints/duplicate")
            duplicate.CreateBody0Rel().SetTargets([base_path])
            duplicate.CreateBody1Rel().SetTargets([lid_path])
            stage.GetRootLayer().Save()
            with pytest.raises(AssertionError, match="joint tree"):
                download_and_wrap_central_asset(URL)

            duplicate.GetPrim().SetActive(False)
            joint.GetBody1Rel().ClearTargets(True)
            stage.GetRootLayer().Save()
            with pytest.raises(AssertionError, match="exactly two"):
                download_and_wrap_central_asset(URL)

            joint.GetBody1Rel().SetTargets([lid_path])
            UsdPhysics.ArticulationRootAPI.Apply(root)
            stage.GetRootLayer().Save()
            prepared = download_and_wrap_central_asset(URL)
            assert prepared.object_type == ObjectType.ARTICULATION
            wrapper_stage = open_wrapper(prepared.usd_path)
            roots = [prim for prim in Usd.PrimRange.Stage(wrapper_stage) if prim.HasAPI(UsdPhysics.ArticulationRootAPI)]
            assert [str(prim.GetPath()) for prim in roots] == ["/Asset/Source"]

            root.RemoveAPI(UsdPhysics.ArticulationRootAPI)
            stage.GetRootLayer().Save()
            prepared = download_and_wrap_central_asset(URL)
            assert open_wrapper(prepared.usd_path).GetDefaultPrim().HasAPI(UsdPhysics.ArticulationRootAPI)

            from isaaclab_arena.assets.simready_object_library import SimReadyUsdObject
            from isaaclab_arena.cli.isaaclab_arena_cli import (
                arena_env_builder_cfg_from_argparse,
                get_isaaclab_arena_cli_parser,
            )
            from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
            from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
            from isaaclab_arena.scene.scene import Scene

            toolbox = SimReadyUsdObject(
                usd_path=prepared.usd_path,
                name="toolbox",
                object_type=ObjectType.ARTICULATION,
            )
            arena = IsaacLabArenaEnvironment(name="simready_articulation", scene=Scene(assets=[toolbox]))
            args = get_isaaclab_arena_cli_parser().parse_args([])
            env = ArenaEnvBuilder(arena, arena_env_builder_cfg_from_argparse(args)).make_registered()
            try:
                env.reset()
                articulation = env.unwrapped.scene["toolbox"]
                assert len(articulation.body_names) == 2
                assert len(articulation.joint_names) == 1
                changed = torch.full_like(articulation.data.joint_pos.torch, 0.25)
                articulation.write_joint_position_to_sim_index(position=changed)
                env.reset()
                torch.testing.assert_close(
                    articulation.data.joint_pos.torch,
                    articulation.data.default_joint_pos.torch,
                )
            finally:
                env.close()
    return True


def test_central_usd_validation():
    from isaaclab_arena.tests.utils.persistent_simulation_app import run_function_with_persistent_simulation_app

    assert run_function_with_persistent_simulation_app(_test_central_usd_validation)


def test_central_download_lists_only_the_selected_package():
    from huggingface_hub.hf_api import RepoFile

    from isaaclab_arena.assets.simready_central_asset_loader import _download_central_asset_package_to_cache

    filenames = ["pallet/simready_usd/pallet.usd", "pallet/textures/color.png"]
    entries = [RepoFile(path=path, size=1, oid="a" * 40) for path in filenames]
    with (
        patch("huggingface_hub.HfApi.list_repo_tree", return_value=iter(entries)) as list_tree,
        patch("huggingface_hub.hf_hub_download", side_effect=lambda **kw: "/cache/" + kw["filename"]) as download,
    ):
        assert _download_central_asset_package_to_cache(URL) == "/cache/" + filenames[0]
    list_tree.assert_called_once_with(
        repo_id="nvidia/simready-assets",
        repo_type="dataset",
        revision=REVISION,
        path_in_repo="pallet",
        recursive=True,
    )
    assert {call.kwargs["filename"] for call in download.call_args_list} == set(filenames)
    assert all(call.kwargs["revision"] == REVISION for call in download.call_args_list)
