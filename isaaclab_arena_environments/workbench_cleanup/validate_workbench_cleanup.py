# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Validate cleanup success, physical counterexamples, and episode reset with applied forces."""

import json
from pathlib import Path

from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext


def validate(builder, args):
    """Run the checked-in recipe and require live success to reject physical counterexamples.

    Args:
        builder: Builder configured with the cleanup environment.
        args: Force runner options, including the recipe and output directory.
    """
    from isaaclab_arena.scripts.force_control_runner import (
        PhysicalCommandRunner,
        _apply_joint_setups,
        load_force_control_recipe,
    )
    from isaaclab_arena.tasks.predicates.spatial import object_in_target
    from isaaclab_arena.tasks.terminations import task_success_from_progress
    from isaaclab_arena.utils.physics_backend import PhysicsBackend

    assert builder.resolved_physics_backend is PhysicsBackend.PHYSX
    recipe = load_force_control_recipe(args.commands)
    env_cfg, env_kwargs = builder.build_env_cfg()
    env_cfg.sim.enable_scene_query_support = True
    env_cfg.recorders = {}
    env_cfg.episode_recorders = {}
    _apply_joint_setups(env_cfg, recipe.joint_setups)
    wrapped_env = builder.make_registered(env_cfg, env_kwargs)
    env = wrapped_env.unwrapped
    results = {}
    try:
        wrapped_env.reset()
        runner = PhysicalCommandRunner(env, args)

        def check(name, expected):
            actual = task_success_from_progress(env).tolist()
            results[name] = {
                "expected_success": expected,
                "success": actual,
                "state": runner._collect_state(),
            }
            assert actual == [expected], f"{name}: expected {expected}, got {actual}"

        runner.step(240)
        check("initial_closed_empty_drawer", False)
        assert not env.progress_tracker.get_subtask_completion().any()
        toolbox = env.scene["toolbox"]
        lid_index = toolbox.data.joint_names.index("joint_top_01_joint_00")
        assert (toolbox.data.joint_pos.torch[:, lid_index] < -1.5).all(), "Toolbox must start open"
        runner.run(recipe)
        check("all_tools_inside_closed_drawer", True)
        assert runner.steps * env.physics_dt < env.cfg.episode_length_s, "Demo must finish before the task timeout"

        joint_commands = [command for command in recipe.commands if command["action"] == "joint"]
        open_drawer, close_drawer = joint_commands
        runner.joint(open_drawer)
        check("reopened_drawer", False)

        runner.lift({"name": "wrench", "height": 1.1, "seconds": 2.0})
        runner.move({
            "name": "wrench",
            "reference": "tabletop",
            "reference_point": "aabb_center",
            "offset": [0.0, 0.0, 0.12],
            "orientation": [0.0, 0.0, 0.0, 1.0],
            "seconds": 3.0,
        })
        runner.release("wrench")
        runner.step(240)
        runner.joint(close_drawer)
        assert env.progress_tracker.get_subtask_completion().all(), "Milestone history must remain recorded"
        assert not object_in_target(env, "wrench", "top_drawer").any()
        check("previously_placed_tool_removed_then_drawer_closed", False)

        runner.joint(open_drawer)
        runner.lift({"name": "wrench", "height": 1.1, "seconds": 2.0})
        runner.move({
            "name": "wrench",
            "reference": "top_drawer",
            "reference_point": "aabb_center",
            "offset": [0.016, 0.08, 0.25],
            "orientation": [0.0, 0.0, 0.0, 1.0],
            "seconds": 3.0,
        })
        runner.move({
            "name": "wrench",
            "reference": "top_drawer",
            "reference_point": "aabb_center",
            "offset": [0.016, 0.08, -0.015],
            "seconds": 2.0,
        })
        runner.step(240)
        assert object_in_target(env, "wrench", "top_drawer").all(), "Floating wrench must be geometrically inside"
        wrench_task = builder.arena_env.task.subtasks[4]
        placement_predicate = wrench_task.get_termination_cfg().success[0].predicate_sequence[-1].predicate
        assert not placement_predicate(env).any(), "Containment without support contact must not count as placement"
        check("floating_tool_without_support_contact", False)

        runner.release("wrench")
        runner.step(240)
        runner.joint(close_drawer)
        runner.wait_final()
        check("tool_restored_and_drawer_closed", True)

        runner.holds.clear()
        runner.joint_holds.clear()
        for obj in env.scene.rigid_objects.values():
            obj.permanent_wrench_composer.reset()
        wrapped_env.reset()
        runner.step(240)
        check("reset_clears_success", False)
        assert not env.progress_tracker.get_subtask_completion().any()
        assert builder.arena_env.task.subtasks[0].openable_object.is_closed(env, threshold=0.03).all()
        assert (toolbox.data.joint_pos.torch[:, lid_index] < -1.5).all(), "Reset must restore the open toolbox"
    finally:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "predicate_checks.json").write_text(json.dumps(results, indent=2) + "\n")
        wrapped_env.close()
    print("PREDICATE_CHECKS_PASSED", list(results), flush=True)


def main():
    """Run physical validation in the configured Arena runtime."""
    from isaaclab_arena_environments.cli import get_arena_builder_from_cli, get_isaaclab_arena_environments_cli_parser

    directory = Path(__file__).resolve().parent
    parser = get_isaaclab_arena_cli_parser()
    parser.add_argument("--output", type=Path, default=Path("outputs/workbench_cleanup/validation"))
    parser.set_defaults(
        env_spec=str(directory / "workbench_cleanup.yaml"),
        device="cpu",
        num_envs=1,
        commands=directory / "workbench_cleanup_force_control.jsonl",
        no_record=True,
        allow_incomplete=False,
        follow_commands=False,
    )
    app_args = parser.parse_args()
    assert app_args.num_envs == 1, "Force-control validation requires one environment"
    with SimulationAppContext(app_args):
        parser = get_isaaclab_arena_environments_cli_parser(parser)
        args = parser.parse_args()
        validate(get_arena_builder_from_cli(args), args)


if __name__ == "__main__":
    main()
