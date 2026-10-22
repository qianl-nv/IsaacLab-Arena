# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import subprocess

import pytest

from isaaclab_arena.tests.utils.constants import TestConstants
from isaaclab_arena.tests.utils.persistent_simulation_app import run_function_with_persistent_simulation_app
from isaaclab_arena.tests.utils.subprocess import run_subprocess

HEADLESS = True
ENABLE_CAMERAS = True

CAMERA_NAME = "wrist_camera"
VARIATION_NAME = f"camera_intrinsics_{CAMERA_NAME}"
EVENT_NAME = f"{CAMERA_NAME}_intrinsics_variation"
# (d_fx, d_fy); distinct signs catch axis/sign swaps.
TEST_DELTAS = (0.1, -0.1)
ASYNC_INITIAL_DELTA = 0.1
ASYNC_RESET_DELTA = 0.5
RENDER_DIFF_THRESHOLD = 1.0
RENDER_ITERS = 3


def get_test_environment(*, camera_intrinsics_variation_enabled: bool):
    """Build a minimal droid-embodiment env with an optional camera intrinsics variation."""
    from isaaclab_arena.embodiments.droid.droid import DroidAbsoluteJointPositionEmbodiment
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
    from isaaclab_arena.scene.scene import Scene
    from isaaclab_arena.variations.camera_intrinsics_variation import CameraIntrinsicsVariationCfg
    from isaaclab_arena.variations.uniform_sampler import UniformSamplerCfg

    embodiment = DroidAbsoluteJointPositionEmbodiment(enable_cameras=ENABLE_CAMERAS)
    if camera_intrinsics_variation_enabled:
        embodiment.get_variation(VARIATION_NAME).apply_cfg(
            CameraIntrinsicsVariationCfg(sampler_cfg=UniformSamplerCfg(low=list(TEST_DELTAS), high=list(TEST_DELTAS)))
        )
        embodiment.get_variation(VARIATION_NAME).enable()

    return IsaacLabArenaEnvironment(name="test_camera_intrinsics_variation", embodiment=embodiment, scene=Scene())


def _test_disabled_camera_intrinsics_variation_not_in_events_cfg(simulation_app):
    from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder

    arena_env = get_test_environment(camera_intrinsics_variation_enabled=False)
    args_cli = get_isaaclab_arena_cli_parser().parse_args(["--num_envs", "1", "--enable_cameras"])
    env_cfg, _ = ArenaEnvBuilder(arena_env, arena_env_builder_cfg_from_argparse(args_cli)).build_env_cfg()

    assert not hasattr(env_cfg.events, EVENT_NAME), (
        f"Disabled variation must not add '{EVENT_NAME}' to env_cfg.events; "
        f"got event fields: {sorted(vars(env_cfg.events))}."
    )
    return True


def _test_enabled_camera_intrinsics_variation_in_events_cfg(simulation_app):
    from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.variations.camera_intrinsics_variation import apply_camera_intrinsics_from_sampler

    arena_env = get_test_environment(camera_intrinsics_variation_enabled=True)
    args_cli = get_isaaclab_arena_cli_parser().parse_args(["--num_envs", "1", "--enable_cameras"])
    env_cfg, _ = ArenaEnvBuilder(arena_env, arena_env_builder_cfg_from_argparse(args_cli)).build_env_cfg()

    assert hasattr(
        env_cfg.events, EVENT_NAME
    ), f"Expected env_cfg.events to contain '{EVENT_NAME}'; got event fields: {sorted(vars(env_cfg.events))}."
    event_cfg = getattr(env_cfg.events, EVENT_NAME)
    assert event_cfg.func is apply_camera_intrinsics_from_sampler
    assert event_cfg.mode == "reset"
    assert event_cfg.params["asset_cfg"].name == CAMERA_NAME
    return True


def _test_disabled_camera_intrinsics_variation_keeps_tiled_camera(simulation_app):
    from isaaclab.sensors import TiledCameraCfg

    from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder

    arena_env = get_test_environment(camera_intrinsics_variation_enabled=False)
    args_cli = get_isaaclab_arena_cli_parser().parse_args(["--num_envs", "1", "--enable_cameras"])
    env_cfg, _ = ArenaEnvBuilder(arena_env, arena_env_builder_cfg_from_argparse(args_cli)).build_env_cfg()

    camera_cfg = getattr(env_cfg.scene, CAMERA_NAME)
    assert isinstance(camera_cfg, TiledCameraCfg), (
        "With the intrinsics variation disabled, the camera should keep the embodiment's "
        f"tiled default; got {type(camera_cfg).__name__}."
    )
    return True


def _test_enabled_camera_intrinsics_variation_forces_untiled_camera(simulation_app):
    from isaaclab.sensors import CameraCfg, TiledCameraCfg

    from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder

    arena_env = get_test_environment(camera_intrinsics_variation_enabled=True)
    args_cli = get_isaaclab_arena_cli_parser().parse_args(["--num_envs", "1", "--enable_cameras"])
    env_cfg, _ = ArenaEnvBuilder(arena_env, arena_env_builder_cfg_from_argparse(args_cli)).build_env_cfg()

    camera_cfg = getattr(env_cfg.scene, CAMERA_NAME)
    assert isinstance(camera_cfg, CameraCfg) and not isinstance(camera_cfg, TiledCameraCfg), (
        "Enabling the intrinsics variation must force the camera untiled so per-env "
        f"perturbations take effect; got {type(camera_cfg).__name__}."
    )
    return True


def _test_camera_intrinsics_variation_realized_at_runtime(simulation_app):
    from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
    from isaaclab_arena.embodiments.droid.droid import DroidCameraCfg
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder

    args_cli = get_isaaclab_arena_cli_parser().parse_args(["--num_envs", "1", "--enable_cameras"])
    env = ArenaEnvBuilder(
        get_test_environment(camera_intrinsics_variation_enabled=True), arena_env_builder_cfg_from_argparse(args_cli)
    ).make_registered()
    env.reset()

    camera = env.unwrapped.scene[CAMERA_NAME]
    sensor_prim = camera._sensor_prims[0]
    # Read nominal apertures from the rig config so the test tracks its source of truth.
    nominal_spawn = getattr(DroidCameraCfg(), CAMERA_NAME).spawn
    d_fx, d_fy = TEST_DELTAS
    expected_horizontal_aperture = nominal_spawn.horizontal_aperture / (1.0 + d_fx)
    expected_vertical_aperture = nominal_spawn.vertical_aperture / (1.0 + d_fy)

    assert sensor_prim.GetHorizontalApertureAttr().Get() == pytest.approx(expected_horizontal_aperture)
    assert sensor_prim.GetVerticalApertureAttr().Get() == pytest.approx(expected_vertical_aperture)

    env.close()
    return True


def _test_camera_intrinsics_async_reset_keeps_other_render_unchanged(simulation_app):
    """Resetting env 0 with new intrinsics must not change env 1's RTX render."""
    import torch

    from isaaclab_arena.assets.registries import AssetRegistry
    from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
    from isaaclab_arena.embodiments.franka.franka import FrankaIKEmbodiment
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
    from isaaclab_arena.scene.scene import Scene
    from isaaclab_arena.variations.camera_intrinsics_variation import CameraIntrinsicsVariationCfg
    from isaaclab_arena.variations.uniform_sampler import UniformSamplerCfg

    camera_name = "wrist_cam"
    variation_name = f"camera_intrinsics_{camera_name}"
    event_name = f"{camera_name}_intrinsics_variation"
    embodiment = FrankaIKEmbodiment(enable_cameras=ENABLE_CAMERAS)
    embodiment.camera_config.wrist_cam.height = 180
    embodiment.camera_config.wrist_cam.width = 240
    variation = embodiment.get_variation(variation_name)
    variation.apply_cfg(
        CameraIntrinsicsVariationCfg(
            sampler_cfg=UniformSamplerCfg(
                low=[ASYNC_INITIAL_DELTA, ASYNC_INITIAL_DELTA],
                high=[ASYNC_INITIAL_DELTA, ASYNC_INITIAL_DELTA],
            )
        )
    )
    variation.enable()

    asset_registry = AssetRegistry()
    scene = Scene(
        assets=[
            asset_registry.get_asset_by_name("maple_table_robolab")(),
            asset_registry.get_asset_by_name("light")(),
            asset_registry.get_asset_by_name("directional_light")(),
        ]
    )
    arena_env = IsaacLabArenaEnvironment(
        name="test_camera_intrinsics_async_reset",
        embodiment=embodiment,
        scene=scene,
    )
    args_cli = get_isaaclab_arena_cli_parser().parse_args(["--num_envs", "2", "--enable_cameras"])
    env = ArenaEnvBuilder(arena_env, arena_env_builder_cfg_from_argparse(args_cli)).make_registered()
    env.reset()

    base_env = env.unwrapped
    camera = base_env.scene[camera_name]

    def render_rgb() -> torch.Tensor:
        for _ in range(RENDER_ITERS):
            base_env.sim.render()
        camera.update(dt=0.0, force_recompute=True)
        return camera.data.output["rgb"].detach().float().cpu().clone()

    before_intrinsics = camera.data.intrinsic_matrices.torch.detach().cpu().clone()
    before_rgb = render_rgb()
    assert (before_rgb[1] > 0).float().mean().item() > 0.01, "Env 1 RTX render is unexpectedly blank."

    # Force env 0's next reset to use a substantially different focal length.
    sampler = base_env.event_manager.get_term_cfg(event_name).params["sampler"]
    sampler.low.fill_(ASYNC_RESET_DELTA)
    sampler.high.fill_(ASYNC_RESET_DELTA)
    base_env.reset(env_ids=torch.tensor([0], device=base_env.device))

    after_intrinsics = camera.data.intrinsic_matrices.torch.detach().cpu().clone()
    after_rgb = render_rgb()
    assert not torch.equal(after_intrinsics[0], before_intrinsics[0]), "Env 0 intrinsics did not change on reset."
    assert torch.equal(after_intrinsics[1], before_intrinsics[1]), "Env 1 reported intrinsics changed without a reset."

    env_1_render_difference = (after_rgb[1] - before_rgb[1]).abs().mean().item()
    env.close()
    assert env_1_render_difference < RENDER_DIFF_THRESHOLD, (
        "Resetting only env 0 changed env 1's RTX render despite env 1 retaining its reported intrinsics: "
        f"mean absolute pixel difference {env_1_render_difference:.4f} >= {RENDER_DIFF_THRESHOLD}."
    )
    return True


def _run_camera_intrinsics_variation_realized_at_runtime():
    """Run the runtime intrinsics check in a disposable Kit process."""
    from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
    from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext

    args_cli = get_isaaclab_arena_cli_parser().parse_args([])
    args_cli.enable_cameras = ENABLE_CAMERAS
    if not HEADLESS:
        args_cli.visualizer = ["kit"]
    with SimulationAppContext(args_cli) as simulation_app_context:
        assert _test_camera_intrinsics_variation_realized_at_runtime(simulation_app_context.app_launcher.app)


def _run_camera_intrinsics_async_reset():
    """Run the multi-environment RTX regression check in a disposable Kit process."""
    from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
    from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext

    args_cli = get_isaaclab_arena_cli_parser().parse_args([])
    args_cli.enable_cameras = ENABLE_CAMERAS
    with SimulationAppContext(args_cli) as simulation_app_context:
        assert _test_camera_intrinsics_async_reset_keeps_other_render_unchanged(simulation_app_context.app_launcher.app)


@pytest.mark.with_cameras
def test_disabled_camera_intrinsics_variation_not_in_events_cfg():
    assert run_function_with_persistent_simulation_app(
        _test_disabled_camera_intrinsics_variation_not_in_events_cfg,
        headless=HEADLESS,
        enable_cameras=ENABLE_CAMERAS,
    )


@pytest.mark.with_cameras
def test_enabled_camera_intrinsics_variation_in_events_cfg():
    assert run_function_with_persistent_simulation_app(
        _test_enabled_camera_intrinsics_variation_in_events_cfg,
        headless=HEADLESS,
        enable_cameras=ENABLE_CAMERAS,
    )


@pytest.mark.with_cameras
def test_disabled_camera_intrinsics_variation_keeps_tiled_camera():
    assert run_function_with_persistent_simulation_app(
        _test_disabled_camera_intrinsics_variation_keeps_tiled_camera,
        headless=HEADLESS,
        enable_cameras=ENABLE_CAMERAS,
    )


@pytest.mark.with_cameras
def test_enabled_camera_intrinsics_variation_forces_untiled_camera():
    assert run_function_with_persistent_simulation_app(
        _test_enabled_camera_intrinsics_variation_forces_untiled_camera,
        headless=HEADLESS,
        enable_cameras=ENABLE_CAMERAS,
    )


@pytest.mark.with_cameras
@pytest.mark.with_subprocess
def test_camera_intrinsics_variation_realized_at_runtime():
    # Lab 3.0 does not fully release the untiled RTX/Replicator resources used by this test
    # when its USD stage is replaced. Keep that state out of the remaining camera tests.
    run_subprocess([TestConstants.python_path, __file__])


@pytest.mark.with_cameras
@pytest.mark.with_subprocess
@pytest.mark.xfail(
    raises=subprocess.CalledProcessError,
    reason="Isaac RTX currently renders every environment with environment 0's projection.",
    strict=True,
)
def test_camera_intrinsics_async_reset_keeps_other_render_unchanged():
    """An asynchronous intrinsics reset must not alter non-reset environments' RTX images."""
    run_subprocess([TestConstants.python_path, __file__, "--test-async-reset"])


if __name__ == "__main__":
    import sys

    if "--test-async-reset" in sys.argv:
        _run_camera_intrinsics_async_reset()
    else:
        _run_camera_intrinsics_variation_realized_at_runtime()
