# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import numpy as np
import traceback

from isaaclab_arena.tests.utils.subprocess import run_simulation_app_function

NUM_STEPS = 5
HEADLESS = True
POSITION_EPS = 5e-2


def _test_droid_static_pose_per_env_reset(simulation_app) -> bool:
    """Verify static relation placement restores distinct Droid poses per environment on reset."""

    import torch

    from isaaclab_arena.assets.registries import AssetRegistry
    from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
    from isaaclab_arena.relations.object_placer_params import ObjectPlacerParams
    from isaaclab_arena.relations.relations import IsAnchor, On
    from isaaclab_arena.scene.scene import Scene
    from isaaclab_arena.utils.pose import Pose, PosePerEnv

    env = None
    try:
        asset_registry = AssetRegistry()
        kitchen = asset_registry.get_asset_by_name("kitchen")()
        kitchen.set_initial_pose(Pose(position_xyz=(0.0, 0.0, 0.0), rotation_xyzw=(0.0, 0.0, 0.0, 1.0)))
        kitchen.add_relation(IsAnchor())

        droid = asset_registry.get_asset_by_name("droid_abs_joint_pos")(stand_height_m=0.8)
        droid.add_relation(On(kitchen, clearance_m=0.0))

        arena_env = IsaacLabArenaEnvironment(
            name="droid_static_pose_per_env_reset",
            embodiment=droid,
            scene=Scene(assets=[kitchen]),
            placer_params=ObjectPlacerParams(
                placement_seed=17,
                resolve_on_reset=False,
                apply_positions_to_objects=False,
            ),
        )
        args_cli = get_isaaclab_arena_cli_parser().parse_args([])
        builder_cfg = arena_env_builder_cfg_from_argparse(args_cli)
        builder_cfg.num_envs = 2
        builder_cfg.solve_relations = True
        builder_cfg.resolve_on_reset = False
        builder = ArenaEnvBuilder(arena_env, builder_cfg)
        env = builder.make_registered()
        env.reset()

        initial_pose = droid.get_initial_pose()
        assert isinstance(initial_pose, PosePerEnv), f"Expected PosePerEnv, got {type(initial_pose).__name__}"
        assert len(initial_pose.poses) == 2

        robot = env.unwrapped.scene["robot"]
        env_origins = env.unwrapped.scene.env_origins

        env_origins_np = env_origins.detach().cpu().numpy()

        def _relative_robot_positions() -> np.ndarray:
            positions = robot.data.root_link_pose_w.torch[:, :3].detach().cpu().numpy()
            return positions - env_origins_np

        for env_idx in range(2):
            expected = np.array(initial_pose.poses[env_idx].position_xyz)
            expected[2] += droid._robot_base_z_offset
            robot_error = np.linalg.norm(_relative_robot_positions()[env_idx] - expected)
            assert robot_error < POSITION_EPS, f"env {env_idx} robot error {robot_error}"

        assert (
            np.linalg.norm(_relative_robot_positions()[0] - _relative_robot_positions()[1]) > 1e-3
        ), "Expected distinct robot placements across environments"

        for _ in range(NUM_STEPS):
            with torch.inference_mode():
                actions = torch.zeros(env.action_space.shape, device=env.unwrapped.device)
                env.step(actions)

        env.reset(options={"env_ids": [1]})
        expected_env1 = np.array(initial_pose.poses[1].position_xyz)
        expected_env1[2] += droid._robot_base_z_offset
        robot_error = np.linalg.norm(_relative_robot_positions()[1] - expected_env1)
        assert robot_error < POSITION_EPS, f"env 1 robot error after partial reset {robot_error}"

    except Exception as exc:
        print(f"Error: {exc}")
        traceback.print_exc()
        return False
    finally:
        if env is not None:
            env.close()

    return True


def test_droid_static_pose_per_env_reset():
    """Pytest entry point for static multi-env Droid placement reset."""
    result = run_simulation_app_function(_test_droid_static_pose_per_env_reset, headless=HEADLESS)
    assert result, f"Test {test_droid_static_pose_per_env_reset.__name__} failed"


if __name__ == "__main__":
    test_droid_static_pose_per_env_reset()
