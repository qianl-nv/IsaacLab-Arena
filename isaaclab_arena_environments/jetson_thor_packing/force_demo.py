# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pack the Thor kit using bounded physical forces, and record native Arena success."""

import argparse
import json
from pathlib import Path

from isaaclab.app import AppLauncher

from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext
from isaaclab_arena_environments.workbench_cleanup.force_demo import ForceDemo

# The reusable demonstration harness supplies wrenches, smooth motion, viewport capture,
# direct physics stepping, and progress logging. No pose/state writes are used for packing.
PLACEMENTS = [
    ("ac_cable_us", [-0.144, 0.0, 0.008], "Place US AC lead in the left compartment"),
    ("ac_cable_eu", [-0.097, 0.0, 0.008], "Place EU AC lead beside the first lead"),
    ("usb_cable", [-0.021, -0.049, 0.009], "Place USB-A / USB-C cable in the middle compartment"),
    ("power_supply", [0.099, 0.0, 0.009], "Place power adapter and captive lead in the right housing"),
    ("board_tray", [0.0, 0.0, 0.084], "Seat the board tray above the packed accessories"),
    ("thor_board", [0.0, 0.0, 0.089], "Place Jetson AGX Thor into the lined upper tray"),
]


class ThorPackingDemo(ForceDemo):
    """Apply the existing force demo harness to the six packing subtasks."""

    def _add_cable(self):
        """The Blender assets already contain complete rigid cable assemblies."""

    def step(self, count=1):
        if getattr(self, "order_probe", None) is None:
            super().step(count)
            return
        for _ in range(count):
            super().step()
            if self.steps % self.env.cfg.decimation == 0:
                self.order_probe.step(self.env, step_index=self.env.episode_length_buf)

    def place(self, name, t_C_goal):
        t_W_C = self.env.arena_world.get_position_w("carton")[0].tolist()
        t_W_goal = [a + b for a, b in zip(t_W_C, t_C_goal)]
        t_W_start = self.env.arena_world.get_position_w(name)[0].tolist()
        clearance = t_W_C[2] + 0.26
        self.move(name, [t_W_start[0], t_W_start[1], clearance], seconds=1.4, orientation=[0, 0, 0, 1])
        self.move(name, [t_W_goal[0], t_W_goal[1], clearance], seconds=1.8, orientation=[0, 0, 0, 1])
        self.move(name, t_W_goal, seconds=2.2, orientation=[0, 0, 0, 1])
        self.release(name)
        self.step(180)

    def task_success(self):
        from isaaclab_arena.tasks.terminations import task_success_from_progress

        return task_success_from_progress(self.env).all().item()

    def check_wrong_compartment(self):
        """A cable touching a different receptacle must not satisfy its own task."""
        self.place("usb_cable", [-0.12, 0.0, 0.009])
        criterion = self.env.cfg.task_progress.success_criteria[2]
        entered = criterion.predicate_sequence[0](self.env).any().item()
        assert not entered, "USB cable in the AC bay incorrectly passed containment"
        self.move("usb_cable", [0, 0.11, 1.02], seconds=1.0)
        self.move("usb_cable", [0.16, -0.24, 1.02], seconds=1.4)
        self.move("usb_cable", [0.16, -0.24, 0.755], seconds=1.5)
        self.release("usb_cable")
        self.step(180)
        return {"wrong_compartment_rejected": True}

    def run(self):
        try:
            if self.viewport is not None:
                self.env.sim.set_camera_view(eye=[0.18, -0.36, 2.35], target=[0.0, 0.0, 0.82])
            self.step(240)
            assert not self.task_success(), "Scattered initial state must not pass"
            checks = {"initial_state_rejected": True}
            if self.args.inspect:
                self.mark(0, "start", "Scattered kit and empty carton")
                return
            if self.args.negative_checks:
                checks.update(self.check_wrong_compartment())
            for index, (name, t_C_goal, title) in enumerate(PLACEMENTS):
                self.mark(index, "start", title)
                self.place(name, t_C_goal)
                self.require(index)
                self.mark(index, "end", title)
                assert not self.holds, "Every placement must be released before it completes"
            self.step(360)
            self.wait_for_final()
            assert self.task_success(), f"Final current conditions failed: {self._criterion_status()}"
            if self.args.negative_checks:
                from dataclasses import replace

                from isaaclab_arena.progress_tracking.progress_tracker import ProgressTracker

                # Activate a fresh board-placement criterion while the board is already packed.
                # It must wait for a NEW entry; merely remaining settled must not count.
                criterion = replace(self.env.cfg.task_progress.success_criteria[-1], parent_subtask_idx=0)
                self.order_probe = ProgressTracker(
                    [criterion],
                    self.env.num_envs,
                    self.env.device,
                    env=self.env,
                    subtasks_are_sequential=True,
                    desired_subtask_success_state=[True],
                )
                self.step(120)
                assert not self.order_probe.is_complete().any().item(), "A prepacked board must not count as new entry"
                checks["board_packed_before_activation_rejected"] = True
                self.lift("thor_board", 1.06, seconds=1.4)
                self.step(60)
                assert not self.task_success(), "Removing the packed board must revoke final success"
                checks["removed_board_revokes_success"] = True
                self.place("thor_board", PLACEMENTS[-1][1])
                self.wait_for_final()
                assert self.task_success(), "Replacing the board must restore final success"
                assert self.order_probe.is_complete().all().item(), "A new settled entry must satisfy the active task"
                self.order_probe = None
                checks["new_entry_after_activation_accepted"] = True
                checks["replacement_restores_success"] = True
            if self.viewport is not None:
                self.env.sim.set_camera_view(eye=[0.52, -0.45, 1.44], target=[0.12, 0.11, 0.86])
                self.step(240)
            self.mark(6, "end", "All six parts settled; Arena task success = true")
            self.env.termination_manager.compute()
            success_term = self.env.termination_manager.get_term("success").tolist()
            assert all(success_term), "Arena's success termination term must agree with the progress tracker"
            report = {
                "mode": "scripted_physics_forces",
                "robot": None,
                "success": self.task_success(),
                "arena_success_termination": success_term,
                "subtasks": self.env.progress_tracker.get_subtask_completion().tolist(),
                "current_predicates": self._criterion_status(),
                "checks": checks,
                "active_external_force_holds": list(self.holds),
                "physics_steps": self.steps,
                "simulation_time_s": self.steps * self.env.physics_dt,
                "video_frames": self.frames,
                "final_poses": {name: self.env.arena_world.get_pose_w(name).tolist() for name, _, _ in PLACEMENTS},
                "final_linear_velocities": {
                    name: self.env.arena_world.get_root_linear_velocity_w(name).tolist() for name, _, _ in PLACEMENTS
                },
                "events": self.events,
                "limitations": ["Photo-estimated packaging and accessory dimensions; rigid coils and cardboard."],
            }
            if self.args.negative_checks:
                self.env.reset()
                self.step(120)
                assert not self.task_success(), "Reset must clear final success"
                assert not self.env.progress_tracker.get_subtask_completion().any().item()
                report["checks"]["reset_clears_success"] = True
            (self.out / "validation.json").write_text(json.dumps(report, indent=2))
            print("TASK_SUCCESS", json.dumps(report), flush=True)
        finally:
            if self.writer is not None:
                self.writer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    AppLauncher.add_app_launcher_args(parser)
    parser.add_argument("--output", type=Path, default=Path("artifacts/jetson_thor_packing/demo"))
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--negative-checks", action="store_true")
    parser.set_defaults(device="cpu", visualizer=["kit"], task=1)
    args = parser.parse_args()
    with SimulationAppContext(args):
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
        from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
        from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

        spec = ArenaEnvGraphSpec.from_yaml(Path(__file__).with_name("task.yaml"))
        builder = ArenaEnvBuilder(
            spec.to_arena_env(),
            ArenaEnvBuilderCfg(
                device="cpu",
                num_envs=1,
                disable_fabric=False,
                placement_seed=17,
            ),
        )
        cfg, kwargs = builder.build_env_cfg()
        cfg.sim.enable_scene_query_support = True
        env = builder.make_registered(cfg, kwargs)
        try:
            env.reset()
            ThorPackingDemo(env.unwrapped, args).run()
        finally:
            env.close()


if __name__ == "__main__":
    main()
