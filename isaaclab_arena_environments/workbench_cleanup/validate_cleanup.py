# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Validate cleanup and false-success cases using physical force-control commands."""

from __future__ import annotations

import json
import sys

from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
from isaaclab_arena.scripts.force_control_runner import (
    PhysicalCommandRunner,
    _add_runner_args,
    _apply_joint_setups,
    _assert_runner_args,
    load_force_control_recipe,
)
from isaaclab_arena.utils.hydra_overrides import assert_hydra_overrides
from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext
from isaaclab_arena.utils.physics_backend import PhysicsBackend
from isaaclab_arena_environments.cli import get_arena_builder_from_cli, get_isaaclab_arena_environments_cli_parser


class CleanupValidationRunner(PhysicalCommandRunner):
    """Run the shared recipe and verify the native task's current success conditions."""

    def __init__(self, env, args):
        super().__init__(env, args)
        self.checks = []

    def assert_success(self, label: str, expected: bool) -> None:
        """Record and assert the current native success result."""
        from isaaclab_arena.tasks.terminations import task_success_from_progress

        actual = task_success_from_progress(self.env).tolist()
        self.checks.append({
            "case": label,
            "expected_success": expected,
            "actual_success": actual,
            "subtasks": self._task_completion().tolist(),
            "simulation_time_s": self.steps * self.env.physics_dt,
        })
        (self.output / "semantic_checks.json").write_text(json.dumps(self.checks, indent=2) + "\n")
        assert all(value == expected for value in actual), f"{label}: expected {expected}, got {actual}"

    def mark(self, index: int, boundary: str, title: str) -> None:
        super().mark(index, boundary, title)
        if index == 0 and boundary == "start":
            self.assert_success("closed_empty_drawer", False)
            assert not self._task_completion().any().item(), "Progress must start empty."
            self.verify_initial_scene()
        if boundary == "end":
            self.assert_success(f"after_subtask_{index}", index == 6)

    def verify_initial_scene(self) -> None:
        """Check the open toolbox and the left-side fixtures after physical settling."""
        from isaaclab.sim import get_current_stage
        from pxr import Usd, UsdGeom, UsdPhysics

        toolbox = self.env.scene["toolbox"]
        lid_id = toolbox.data.joint_names.index("joint_body_01_joint_00")
        assert (toolbox.data.joint_pos.torch[:, lid_id] < -2.0).all().item(), "Toolbox must start open."
        cabinet_y = self.env.arena_world.get_position_w("cabinet")[:, 1]
        scope_y = self.env.arena_world.get_position_w("oscilloscope")[:, 1]
        assert (cabinet_y < scope_y).all().item()
        for name in ("slotted_screwdriver", "torx_screwdriver", "phillips_screwdriver", "wrench_1", "wrench_2"):
            t_W = self.env.arena_world.get_position_w(name)
            assert (scope_y < t_W[:, 1]).all().item(), f"Oscilloscope must be left of {name}."
            assert ((t_W[:, 2] > 0.64) & (t_W[:, 2] < 0.85)).all().item(), f"{name} must rest on the bench."
            root = get_current_stage().GetPrimAtPath(f"/World/envs/env_0/{name}")
            for prim in Usd.PrimRange(root, Usd.TraverseInstanceProxies()):
                if prim.IsA(UsdGeom.Mesh) and prim.HasAPI(UsdPhysics.CollisionAPI):
                    assert UsdPhysics.MeshCollisionAPI(prim).GetApproximationAttr().Get() == "convexHull"
                if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    assert prim.GetAttribute("physxRigidBody:angularDamping").Get() == 5.0

    def verify_current_conditions_and_reset(self) -> None:
        """Invalidate completed milestones physically, restore success, and verify reset isolation."""
        from isaaclab.managers import SceneEntityCfg

        from isaaclab_arena.tasks.predicates.spatial import object_in_contact_with_target, object_in_target

        joint = {
            "name": "cabinet",
            "joint_name": "joint_part_01_joint_00",
            "seconds": 4.0,
            "gain": 600.0,
            "damping": 50.0,
            "limit": 100.0,
        }
        self.joint({**joint, "normalized_goal": 0.98})
        self.assert_success("reopened_after_success", False)
        self.lift({"name": "wrench_2", "height": 1.20, "seconds": 2.0})
        self.joint({**joint, "normalized_goal": 0.0})
        self.step(240)
        self.assert_success("closed_with_previously_completed_tool_removed", False)
        assert self._task_completion().all().item(), "This case must test already-completed milestones."

        self.joint({**joint, "normalized_goal": 0.98})
        target = {
            "name": "wrench_2",
            "reference": "top_drawer",
            "reference_point": "aabb_center",
            "orientation": [0.0, 0.0, 0.0, 1.0],
            "seconds": 3.0,
        }
        self.move({**target, "offset": [0.06, 0.24, 0.01]})
        self.step(240)
        assert object_in_target(self.env, "wrench_2", "top_drawer").all().item()
        sensor = SceneEntityCfg("contact_sensor_wrench_2_in_top_drawer")
        assert not object_in_contact_with_target(self.env, sensor, 0.01).any().item()
        placement = self._criterion_status()["subtask_5/object_in"][-1]
        assert not any(placement), "A contained but unsupported tool must not satisfy placement."
        self.assert_success("tool_hovering_inside_drawer", False)

        self.move({**target, "offset": [0.06, 0.24, -0.03]})
        self.release("wrench_2")
        self.step(240)
        self.joint({**joint, "normalized_goal": 0.0})
        self.wait_final()
        self.assert_success("restored_all_tools_and_closed", True)
        self.holds.clear()
        self.joint_holds.clear()
        self.env.reset()
        self.step(240)
        self.assert_success("reset_clears_previous_episode", False)
        assert not self._task_completion().any().item()
        self.verify_initial_scene()
        print("CLEANUP_SEMANTICS_PASSED", json.dumps(self.checks), flush=True)


def main() -> None:
    """Build the YAML environment and validate its force-based cleanup demonstration."""
    parser = get_isaaclab_arena_cli_parser()
    _add_runner_args(parser)
    parser.set_defaults(device="cpu", visualizer=["kit"])
    parser.allow_abbrev = False
    cli_args = sys.argv[1:]
    app_args, _ = parser.parse_known_args(cli_args)
    _assert_runner_args(app_args)
    with SimulationAppContext(app_args):
        parser = get_isaaclab_arena_environments_cli_parser(parser)
        args, overrides = parser.parse_known_args(cli_args)
        assert_hydra_overrides(overrides, parser)
        _assert_runner_args(args)
        assert not args.follow_commands and not args.allow_incomplete
        recipe = load_force_control_recipe(args.commands)
        builder = get_arena_builder_from_cli(args, hydra_overrides=overrides)
        assert builder.resolved_physics_backend is PhysicsBackend.PHYSX
        env_cfg, env_kwargs = builder.build_env_cfg()
        env_cfg.sim.enable_scene_query_support = True
        env_cfg.recorders = {}
        env_cfg.episode_recorders = {}
        _apply_joint_setups(env_cfg, recipe.joint_setups)
        env = builder.make_registered(env_cfg, env_kwargs)
        try:
            env.reset()
            runner = CleanupValidationRunner(env.unwrapped, args)
            runner.run(recipe)
            # run() closes the video; semantic checks continue without recording.
            runner.viewport = None
            runner.verify_current_conditions_and_reset()
        finally:
            env.close()


if __name__ == "__main__":
    main()
