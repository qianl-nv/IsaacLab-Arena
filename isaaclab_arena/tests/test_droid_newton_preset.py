# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for backend-specific DROID configuration."""

from pathlib import Path

from isaaclab_arena.tests.utils.persistent_simulation_app import run_function_with_persistent_simulation_app

HEADLESS = True
_GRIPPER_JOINT_NAMES = {
    "finger_joint",
    "left_inner_finger_joint",
    "left_inner_finger_knuckle_joint",
    "right_outer_knuckle_joint",
    "right_inner_finger_joint",
    "right_inner_finger_knuckle_joint",
}


def _build_droid_env_cfg(preset: str):
    from isaaclab_arena.assets.registries import AssetRegistry
    from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
    from isaaclab_arena.embodiments.droid.droid import DroidAbsoluteJointPositionEmbodiment
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
    from isaaclab_arena.scene.scene import Scene

    args_cli = get_isaaclab_arena_cli_parser().parse_args(["--num_envs", "1", "--presets", preset])
    table = AssetRegistry().get_asset_by_name("packing_table")()
    arena_env = IsaacLabArenaEnvironment(
        name=f"test_droid_{preset}_preset",
        embodiment=DroidAbsoluteJointPositionEmbodiment(),
        scene=Scene(assets=[table]),
    )
    builder = ArenaEnvBuilder(arena_env, arena_env_builder_cfg_from_argparse(args_cli))
    env_cfg, _ = builder.compose_manager_cfg()
    return env_cfg


def _test_droid_newton_preset(simulation_app) -> bool:
    from isaaclab_newton.physics import NewtonCfg
    from pxr import Usd, UsdGeom, UsdPhysics

    from isaaclab_arena.embodiments.droid.newton import _is_newton_compatible

    env_cfg = _build_droid_env_cfg("newton")
    assert isinstance(env_cfg.sim.physics, NewtonCfg)
    assert env_cfg.scene.replicate_physics

    robot_cfg = env_cfg.scene.robot
    usd_path = Path(robot_cfg.spawn.usd_path)
    assert usd_path.is_file()
    assert usd_path.stem.endswith("_newton_droid")
    assert _is_newton_compatible(usd_path, gravity_compensation=1.0)
    assert robot_cfg.spawn.rigid_props.disable_gravity is False

    gripper_actuator = robot_cfg.actuators["gripper"]
    assert set(gripper_actuator.joint_names_expr) == _GRIPPER_JOINT_NAMES
    assert gripper_actuator.effort_limit_sim == 5.0
    assert gripper_actuator.velocity_limit_sim == 1.0
    assert gripper_actuator.stiffness == 20.0
    assert gripper_actuator.damping == 5.0
    assert gripper_actuator.armature == 0.1

    gripper_action = env_cfg.actions.gripper_action
    assert set(gripper_action.joint_names) == _GRIPPER_JOINT_NAMES
    assert gripper_action.open_command_expr == dict.fromkeys(_GRIPPER_JOINT_NAMES, 0.0)
    assert set(gripper_action.close_command_expr) == _GRIPPER_JOINT_NAMES
    assert env_cfg.events.randomize_franka_joint_state.params["asset_cfg"].joint_names == ["panda_joint.*"]

    stage = Usd.Stage.Open(str(usd_path))
    assert stage is not None
    pads = [prim for prim in stage.Traverse() if prim.IsA(UsdGeom.Mesh) and prim.GetName() == "newton_pad_collision"]
    assert len(pads) == 2
    assert all(UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get() for prim in pads)
    return True


def _test_droid_physx_preset_is_unchanged(simulation_app) -> bool:
    from isaaclab_physx.physics import PhysxCfg

    env_cfg = _build_droid_env_cfg("physx")
    assert isinstance(env_cfg.sim.physics, PhysxCfg)
    assert not env_cfg.scene.replicate_physics

    robot_cfg = env_cfg.scene.robot
    assert not Path(robot_cfg.spawn.usd_path).stem.endswith("_newton_droid")
    assert robot_cfg.spawn.rigid_props.disable_gravity is True
    assert robot_cfg.actuators["gripper"].joint_names_expr == ["finger_joint"]
    assert env_cfg.actions.gripper_action.joint_names == ["finger_joint"]
    return True


def test_droid_newton_preset():
    assert run_function_with_persistent_simulation_app(_test_droid_newton_preset, headless=HEADLESS)


def test_droid_physx_preset_is_unchanged():
    assert run_function_with_persistent_simulation_app(_test_droid_physx_preset_is_unchanged, headless=HEADLESS)
