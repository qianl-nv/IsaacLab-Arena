# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Simulation tests for the Newton DROID differential IK embodiment."""

from __future__ import annotations

import gymnasium as gym
import torch

import warp as wp

from isaaclab_arena.assets.device_library import KeyboardCfg
from isaaclab_arena.tests.utils.persistent_simulation_app import run_function_with_persistent_simulation_app

HEADLESS = True
SETTLE_STEPS = 10
HOLD_STEPS = 30
LIFT_STEPS = 20
HOLD_TOLERANCE_M = 0.005
TARGET_LIFT_M = 0.05
LIFT_TOLERANCE_M = 0.025
KEYBOARD_POS_SENSITIVITY = KeyboardCfg().pos_sensitivity


def _newton_droid_env_cfg_callback(env_cfg):
    """Apply the Newton sim settings used by contact-rich DROID manipulation envs."""
    from isaaclab_newton.physics import HydroelasticSDFCfg, NewtonCollisionPipelineCfg

    from isaaclab_arena.environments.isaaclab_arena_manager_based_env_cfg import ArenaPhysicsCfg

    env_cfg.sim.dt = 1.0 / 240.0
    env_cfg.decimation = 8
    env_cfg.sim.render_interval = 8
    env_cfg.sim.physics = ArenaPhysicsCfg().newton
    env_cfg.sim.physics.num_substeps = 4
    env_cfg.sim.physics.default_shape_cfg.gap = 0.0
    env_cfg.sim.physics.solver_cfg.ls_iterations = 50
    env_cfg.sim.physics.solver_cfg.ccd_iterations = 35
    env_cfg.sim.physics.solver_cfg.njmax = 4096
    env_cfg.sim.physics.solver_cfg.nconmax = 4096
    env_cfg.sim.physics.collision_cfg = NewtonCollisionPipelineCfg(
        sdf_hydroelastic_config=HydroelasticSDFCfg(reduce_contacts=True, normal_matching=True)
    )
    env_cfg.scene.env_spacing = 1.5
    env_cfg.scene.replicate_physics = True
    if hasattr(env_cfg.events, "randomize_franka_joint_state"):
        env_cfg.events.randomize_franka_joint_state = None
    return env_cfg


def _build_newton_droid_env(env_name: str):
    """Build a minimal Newton scene with keyboard-teleoperable DROID differential IK."""
    from isaaclab_arena.assets.registries import AssetRegistry, DeviceRegistry
    from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
    from isaaclab_arena.embodiments.droid.droid import DroidNewtonDifferentialIKEmbodiment
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
    from isaaclab_arena.scene.scene import Scene
    from isaaclab_arena.utils.pose import Pose

    args_cli = get_isaaclab_arena_cli_parser().parse_args(["--num_envs", "1"])
    asset_registry = AssetRegistry()
    device_registry = DeviceRegistry()

    background = asset_registry.get_asset_by_name("packing_table")()
    embodiment = DroidNewtonDifferentialIKEmbodiment()
    embodiment.set_initial_pose(Pose(position_xyz=(0.0, 0.0, 1.0), rotation_xyzw=(0.0, 0.0, 0.0, 1.0)))

    teleop_device = device_registry.get_device_by_name("keyboard")()
    arena_env = IsaacLabArenaEnvironment(
        name=env_name,
        embodiment=embodiment,
        scene=Scene(assets=[background]),
        teleop_device=teleop_device,
        env_cfg_callback=_newton_droid_env_cfg_callback,
    )

    if env_name in gym.registry:
        del gym.registry[env_name]

    env = ArenaEnvBuilder(arena_env, arena_env_builder_cfg_from_argparse(args_cli)).make_registered()
    env.reset()
    return env, arena_env.name


def _get_ee_pos_w(env) -> torch.Tensor:
    """Return the Robotiq base link position in the env-local world frame."""
    robot = env.unwrapped.scene["robot"]
    body_idx = robot.data.body_names.index("base_link")
    return wp.to_torch(robot.data.body_pos_w)[0, body_idx, :] - env.unwrapped.scene.env_origins[0]


def _idle_teleop_action(device: torch.device) -> torch.Tensor:
    """Return the action produced by a keyboard with no motion keys pressed."""
    return torch.tensor([[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]], device=device)


def _lift_teleop_action(device: torch.device, pos_sensitivity: float = KEYBOARD_POS_SENSITIVITY) -> torch.Tensor:
    """Return the action produced by holding the keyboard lift key (Q)."""
    return torch.tensor([[0.0, 0.0, pos_sensitivity, 0.0, 0.0, 0.0, 1.0]], device=device)


def _test_newton_droid_ik_holds_without_teleop_command(simulation_app) -> bool:
    """The arm should stay put when the keyboard emits no motion command."""
    env, env_name = _build_newton_droid_env("newton_droid_ik_hold_test")

    try:
        with torch.inference_mode():
            device = env.unwrapped.device
            for _ in range(SETTLE_STEPS):
                env.step(_idle_teleop_action(device))

            initial_ee_pos = _get_ee_pos_w(env)

            for _ in range(HOLD_STEPS):
                env.step(_idle_teleop_action(device))

            final_ee_pos = _get_ee_pos_w(env)
            displacement = torch.norm(final_ee_pos - initial_ee_pos).item()
            assert displacement < HOLD_TOLERANCE_M, (
                f"End effector moved {displacement:.4f} m without a teleop command; "
                f"tolerance is {HOLD_TOLERANCE_M:.4f} m."
            )
    finally:
        env.close()
        if env_name in gym.registry:
            del gym.registry[env_name]

    return True


def _test_newton_droid_ik_lifts_on_teleop_command(simulation_app) -> bool:
    """A sustained keyboard lift command should raise the end effector by roughly 5 cm."""
    env, env_name = _build_newton_droid_env("newton_droid_ik_lift_test")

    try:
        with torch.inference_mode():
            device = env.unwrapped.device
            for _ in range(SETTLE_STEPS):
                env.step(_idle_teleop_action(device))

            initial_ee_pos = _get_ee_pos_w(env)
            lift_action = _lift_teleop_action(device)
            for _ in range(LIFT_STEPS):
                env.step(lift_action)

            final_ee_pos = _get_ee_pos_w(env)
            displacement = final_ee_pos - initial_ee_pos
            lift_z = displacement[2].item()
            horizontal = torch.norm(displacement[:2]).item()

            assert (
                lift_z > TARGET_LIFT_M - LIFT_TOLERANCE_M
            ), f"Expected at least {TARGET_LIFT_M - LIFT_TOLERANCE_M:.3f} m upward motion, got {lift_z:.4f} m."
            assert (
                lift_z < TARGET_LIFT_M + LIFT_TOLERANCE_M + 0.03
            ), f"Expected roughly {TARGET_LIFT_M:.2f} m upward motion, got {lift_z:.4f} m."
            assert (
                lift_z > horizontal
            ), f"Lift should be primarily vertical; dz={lift_z:.4f} m, horizontal={horizontal:.4f} m."
    finally:
        env.close()
        if env_name in gym.registry:
            del gym.registry[env_name]

    return True


def test_newton_droid_ik_holds_without_teleop_command():
    """Pytest entry point for the no-command hold check."""
    assert run_function_with_persistent_simulation_app(
        _test_newton_droid_ik_holds_without_teleop_command,
        headless=HEADLESS,
    )


def test_newton_droid_ik_lifts_on_teleop_command():
    """Pytest entry point for the keyboard lift check."""
    assert run_function_with_persistent_simulation_app(
        _test_newton_droid_ik_lifts_on_teleop_command,
        headless=HEADLESS,
    )
