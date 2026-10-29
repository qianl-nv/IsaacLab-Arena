# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Run DROID workbench IK attempts and report native success or the first physical failure.

Task 3 has a successful recorded rollout. Tasks 1 and 2 are diagnostic candidate plans;
they currently stop at failed grasps or tracking checks rather than reporting completion.
"""

import argparse
import json
import time
from contextlib import contextmanager
from pathlib import Path

from isaaclab.app import AppLauncher

from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    AppLauncher.add_app_launcher_args(parser)
    parser.add_argument("--task", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/workbench_cleanup_droid"))
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--audit-only", action="store_true", help="Check critical IK poses without moving the robot.")
    parser.set_defaults(device="cpu", visualizer=["kit"])
    args = parser.parse_args()
    if args.audit_only:
        args.no_record = True
    started = time.monotonic()
    with SimulationAppContext(args):
        from isaaclab.actuators import ImplicitActuatorCfg

        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
        from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
        from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

        spec = ArenaEnvGraphSpec.from_yaml(Path(__file__).with_name(f"droid_task_{args.task}.yaml"))
        builder = ArenaEnvBuilder(
            spec.to_arena_env(),
            ArenaEnvBuilderCfg(
                device="cpu",
                num_envs=1,
                placement_seed=17,
                recorder_dataset_export_dir_path=str(args.output / f"task_{args.task}"),
                recorder_dataset_filename="episodes",
            ),
        )
        cfg, kwargs = builder.build_env_cfg()
        # These joints remain passive: only the robot's arm and fingers receive commands.
        for name, joint in {
            "socket_set": "case_lid",
            "left_drawers": "joint_drawersA_01_joint_00",
            "oscilloscope": "joint_button_01_joint_00",
        }.items():
            getattr(cfg.scene, name).actuators = {
                "passive": ImplicitActuatorCfg(
                    joint_names_expr=[joint],
                    stiffness=0.0,
                    damping=0.0,
                    effort_limit_sim=100.0,
                ),
            }
        env = builder.make_registered(cfg, kwargs)
        try:
            env.reset()
            demo = DroidDemo(env.unwrapped, args)
            demo.initialize()
            # Settle the newly created articulation constraints before the recorded episode.
            viewport = demo.viewport
            demo.viewport = None
            demo.step(180)
            env.reset()
            demo.initialize()
            demo.steps = 0
            demo.viewport = viewport
            demo.run(started)
        finally:
            env.close()


class DroidDemo:
    """Send bounded IK joint targets to the arm and continuous targets to the fingers."""

    def __init__(self, env, args):
        import torch

        import omni.usd

        self.env, self.args, self.torch = env, args, torch
        self.out = args.output / f"task_{args.task}"
        self.out.mkdir(parents=True, exist_ok=True)
        self.robot = env.scene["robot"]
        self.body_id = self.robot.body_names.index("base_link")
        self.stage = omni.usd.get_context().get_stage()
        self.steps = 0
        self.frames = 0
        self.events = []
        self.motions = []
        self.grip = 0.0
        self.writer = None
        self.viewport = None
        self.last_image = None
        if not args.no_record:
            import imageio.v2 as imageio
            from omni.kit.viewport.utility import get_active_viewport

            self.viewport = get_active_viewport()
            self.viewport.resolution = (1280, 720)
            self.env.sim.set_camera_view(eye=[2.0, -1.85, 1.85], target=[0.1, 0.0, 0.85])
            for _ in range(30):
                self.env.sim.render()
            self.writer = imageio.get_writer(str(self.out / "demo.mp4"), fps=20, codec="libx264", quality=8)

    def initialize(self):
        from isaaclab_arena_environments.workbench_cleanup.droid_ik import DroidWorkbenchIK, pose_to_matrix

        T_W_B = self.robot.data.root_pose_w.torch[0].numpy()
        self.ik = DroidWorkbenchIK(self.stage, "/World/envs/env_0/Robot", pose_to_matrix(T_W_B[:3], T_W_B[3:]))
        self.joint_goal = self.robot.data.joint_pos.torch[:, :7].clone()
        fk = self.ik.forward(self.joint_goal[0].numpy())
        assert self.torch.linalg.vector_norm(self.torch.tensor(fk[:3, 3]) - self.pose()[0, :3]) < 1e-4
        self._add_cable()

    def pose(self):
        from isaaclab.utils.math import combine_frame_transforms

        T_W_E = self.robot.data.body_pose_w.torch[:, self.body_id]
        t_W_G, q_W_G = combine_frame_transforms(
            T_W_E[:, :3],
            T_W_E[:, 3:],
            self.torch.tensor([[0.131, 0.0, 0.0]]),
        )
        return self.torch.cat((t_W_G, q_W_G), dim=-1).clone()

    # Reuse only the existing viewport/cable/display helpers, never its object-force controller.
    from isaaclab_arena_environments.workbench_cleanup.force_demo import ForceDemo as _ViewHelpers

    _capture_frame = _ViewHelpers._capture_frame
    _add_cable = _ViewHelpers._add_cable
    _update_cable = _ViewHelpers._update_cable
    _update_power_display = _ViewHelpers._update_power_display

    def step(self, count=1):
        """Advance PhysX and Arena progress without resetting a successful episode."""
        for _ in range(count):
            action = self.torch.cat((self.joint_goal, self.torch.tensor([[self.grip]])), dim=-1)
            self.env.action_manager.process_action(action)
            self.env.action_manager.apply_action()
            self.env.scene.write_data_to_sim()
            self.env.sim.step(render=False)
            self.env.scene.update(self.env.physics_dt)
            self.steps += 1
            if self.steps % self.env.cfg.decimation == 0:
                self.env.common_step_counter += 1
                self.env.episode_length_buf += 1
                self.env.update_task_progress()
            if self.steps % 6 == 0 and self.viewport is not None:
                if self.args.task == 3:
                    self._update_cable()
                    self._update_power_display()
                self._capture_frame()

    def move(self, t_W_G, euler_xyz_deg, seconds=3.0):
        """Track a smooth Cartesian segment through bounded IK joint targets."""
        import numpy as np
        from scipy.spatial.transform import Rotation, Slerp

        start = self.pose()[0].numpy()
        q_W_G = Rotation.from_euler("xyz", euler_xyz_deg, degrees=True).as_quat()
        slerp = Slerp([0, 1], Rotation.from_quat([start[3:], q_W_G]))
        seed = self.joint_goal[0].numpy()
        max_position_error = max_rotation_error = 0.0
        count = int(seconds / self.env.physics_dt)
        for index in range(count):
            alpha = (index + 1) / count
            alpha = alpha * alpha * (3 - 2 * alpha)
            t_W_goal = (1 - alpha) * start[:3] + alpha * np.array(t_W_G)
            q_W_goal = slerp([alpha]).as_quat()[0]
            seed, position_error, rotation_error = self.ik.solve(t_W_goal, q_W_goal, seed)
            assert (
                position_error < 0.008 and rotation_error < 0.08
            ), f"IK segment failed: {position_error:.4f} m, {rotation_error:.4f} rad at {t_W_goal}"
            max_position_error = max(max_position_error, position_error)
            max_rotation_error = max(max_rotation_error, rotation_error)
            self.joint_goal[0] = self.torch.tensor(seed)
            self.step()
        self.step(60)
        actual = self.pose()[0].tolist()
        record = {
            "target_xyz": list(t_W_G),
            "target_euler_xyz_deg": list(euler_xyz_deg),
            "max_ik_position_error_m": max_position_error,
            "max_ik_rotation_error_rad": max_rotation_error,
            "measured_grasp_pose_xyzw": actual,
            "measured_position_error_m": float(np.linalg.norm(np.array(actual[:3]) - t_W_G)),
        }
        self.motions.append(record)
        print("MOTION", json.dumps(record), flush=True)
        assert record["measured_position_error_m"] < 0.05, "Robot could not track the Cartesian endpoint in physics."

    def joint_move(self, t_W_G, euler_xyz_deg, seconds=3.0, canonical_seed=False):
        """Use bounded endpoint IK and interpolate arm joints for a free-space transit."""
        import numpy as np
        from scipy.spatial.transform import Rotation

        start = self.robot.data.joint_pos.torch[0, :7].numpy().copy()
        seed = self.ik.preferred_joints if canonical_seed else start
        q_W_G = Rotation.from_euler("xyz", euler_xyz_deg, degrees=True).as_quat()
        target, position_error, rotation_error = self.ik.solve(t_W_G, q_W_G, seed, multistart=True)
        assert (
            position_error < 0.005 and rotation_error < 0.05
        ), f"Unreachable IK endpoint: {position_error:.4f} m, {rotation_error:.4f} rad"
        count = int(seconds / self.env.physics_dt)
        for index in range(count):
            alpha = (index + 1) / count
            alpha = alpha * alpha * (3 - 2 * alpha)
            self.joint_goal[0] = self.torch.tensor((1 - alpha) * start + alpha * target)
            self.step()
        self.step(90)
        actual = self.pose()[0].tolist()
        record = {
            "path": "joint interpolation",
            "target_xyz": list(t_W_G),
            "target_euler_xyz_deg": list(euler_xyz_deg),
            "max_ik_position_error_m": position_error,
            "max_ik_rotation_error_rad": rotation_error,
            "measured_grasp_pose_xyzw": actual,
            "measured_position_error_m": float(np.linalg.norm(np.array(actual[:3]) - t_W_G)),
        }
        self.motions.append(record)
        print("MOTION", json.dumps(record), flush=True)
        assert record["measured_position_error_m"] < 0.05, "Robot could not reach the IK endpoint in physics."

    def gripper(self, fraction, steps=180):
        """Command a closing fraction: zero fully open, one fully closed."""
        self.grip = fraction
        self.step(steps)

    def mark(self, index, boundary, title):
        import imageio.v3 as iio

        record = {
            "subtask": index,
            "boundary": boundary,
            "title": title,
            "simulation_time_s": self.steps * self.env.physics_dt,
            "completion": self.env.progress_tracker.get_subtask_completion()[0].tolist(),
            "grasp_pose_xyzw": self.pose()[0].tolist(),
            "arm_joint_positions": self.robot.data.joint_pos.torch[0, :7].tolist(),
            "object_poses_xyzw": {
                name: self.env.arena_world.get_pose_w(name)[0].tolist()
                for name in ("socket_set", "overhead_bin", "power_plug", "oscilloscope", "top_left_drawer")
            },
        }
        if self.viewport is not None:
            self._capture_frame()
            filename = f"{index:02d}_{boundary}.png"
            iio.imwrite(self.out / filename, self.last_image)
            record["viewport"] = filename
        self.events.append(record)
        (self.out / "progress.json").write_text(json.dumps(self.events, indent=2))
        print("SUBTASK", json.dumps(record), flush=True)

    @contextmanager
    def subtask(self, index, title):
        self.mark(index, "start", title)
        try:
            yield
            for _ in range(600):
                if self.env.progress_tracker.get_subtask_completion()[0, index].item():
                    break
                self.step()
        finally:
            self.mark(index, "end", title)
        assert self.env.progress_tracker.get_subtask_completion()[0, index].item(), f"Subtask {index} failed: {title}"

    def audit_reachability(self):
        """Write bounded IK checks; these do not certify collision clearance or grasp stability."""
        import numpy as np
        from scipy.spatial.transform import Rotation

        waypoints = {
            1: [
                ("close_socket_set", [0.02, 0.535, 0.77], [0, 60, 180]),
                ("open_drawer", [0.255, -0.524, 0.583], [90, 50, 180]),
                ("pull_drawer", [0.495, -0.524, 0.583], [90, 50, 180]),
                ("grasp_case_handle", [0.0965, 0.535, 0.715], [0, 90, 90]),
                ("lift_case", [0.0965, 0.535, 0.95], [0, 90, 90]),
                ("place_case_in_drawer", [0.42, -0.524, 0.65], [0, 90, 90]),
                ("close_drawer", [0.27, -0.524, 0.58], [0, 30, 180]),
            ],
            2: [
                ("grasp_bin", [0.066, 0.34, 1.325], [90, 0, 180]),
                ("lift_bin", [0.066, 0.34, 1.52], [90, 0, 180]),
                ("lower_bin", [0.08, 0.23, 0.84], [90, 0, 180]),
                ("return_loaded_bin", [0.066, 0.34, 1.325], [90, 0, 180]),
            ],
            3: [
                ("press_power_button", [0.018, -0.643, 0.696], [0, 50, 180]),
                ("grasp_plug", [-0.132, -0.70, 0.888], [-90, 0, 180]),
                ("withdraw_plug", [0.04, -0.70, 0.888], [-90, 0, 180]),
            ],
        }[self.args.task]
        if self.args.task == 2:
            for name in (
                "slotted_screwdriver",
                "torx_screwdriver",
                "phillips_screwdriver",
                "combination_wrench",
                "small_wrench",
            ):
                T_W_O = self.env.arena_world.get_pose_w(name)[0].numpy()
                R_W_O = Rotation.from_quat(T_W_O[3:])
                t_W_G = T_W_O[:3] + R_W_O.apply([-0.02 if "screwdriver" in name else 0.0, 0, 0.016])
                t_W_G += np.array([0.014, 0, 0.021])
                t_W_G[2] = max(t_W_G[2], 0.707 if "screwdriver" in name else 0.696)
                yaw = R_W_O.as_euler("xyz", degrees=True)[2]
                waypoints.append(("pick_" + name, t_W_G.tolist(), [0, 45, float(yaw + 180)]))
                waypoints.append(("place_" + name, [-0.03, 0.24, 0.84], [0, 45, 180]))
        checks = []
        for name, t_W_G, euler in waypoints:
            q_W_G = Rotation.from_euler("xyz", euler, degrees=True).as_quat()
            joints, pe, re = self.ik.solve(t_W_G, q_W_G, np.array([0, -0.6, 0, -2.2, 0, 2, 0]), multistart=True)
            checks.append({
                "action": name,
                "target_xyz": t_W_G,
                "target_euler_xyz_deg": euler,
                "ik_reachable": pe < 0.005 and re < 0.05,
                "position_error_m": pe,
                "rotation_error_rad": re,
                "arm_joints_rad": joints.tolist(),
                "collision_and_grasp_validation": "Requires physical rollout; not checked by IK",
            })
        (self.out / "reachability.json").write_text(json.dumps(checks, indent=2))
        return checks

    def task_one(self):
        with self.subtask(0, "Close the socket case"):
            self.gripper(1, 120)
            self.joint_move([0.22, 0.535, 0.93], [0, 60, 180], 4)
            self.joint_move([-0.15, 0.535, 0.93], [0, 60, 180], 4)
            self.joint_move([-0.15, 0.535, 0.81], [0, 60, 180])
            self.joint_move([0.02, 0.535, 0.77], [0, 60, 180], 4)
        with self.subtask(1, "Open the top-left drawer"):
            self.joint_move([0.26, 0.535, 0.94], [0, 60, 180])
            self.joint_move([0.37, -0.524, 0.73], [90, 50, 180], 5)
            self.gripper(0, 120)
            self.joint_move([0.255, -0.524, 0.583], [90, 50, 180])
            self.gripper(1)
            self.joint_move([0.495, -0.524, 0.583], [90, 50, 180], 5)
        with self.subtask(2, "Grasp the case and place it in the drawer"):
            self.gripper(0, 120)
            self.joint_move([0.55, -0.524, 0.88], [0, 90, 90])
            self.joint_move([0.20, 0.535, 0.85], [0, 90, 90], 6)
            self.gripper(0.8, 120)
            self.joint_move([0.0965, 0.535, 0.715], [0, 90, 90], 4)
            self.gripper(1)
            self.move([0.0965, 0.535, 0.95], [0, 90, 90], 4)
            assert self.env.arena_world.get_position_w("socket_set")[0, 2] > 0.73, "Case grasp did not lift the case."
            self.joint_move([0.42, -0.524, 0.80], [0, 90, 90], 6)
            self.move([0.42, -0.524, 0.65], [0, 90, 90], 4)
            self.gripper(0)
            self.move([0.55, -0.524, 0.80], [0, 90, 90])
        with self.subtask(3, "Close the loaded drawer"):
            self.gripper(1, 120)
            self.joint_move([0.57, -0.524, 0.67], [0, 30, 180], 4)
            self.move([0.57, -0.524, 0.58], [0, 30, 180])
            self.move([0.270, -0.524, 0.58], [0, 30, 180], 5)
            self.move([0.55, -0.524, 0.70], [0, 30, 180])

    def move_grasped_object(self, name, t_W_O, q_W_O, seconds=4.0):
        """Compute a robot target from the measured grasp transform, without attaching the object."""
        import numpy as np
        from scipy.spatial.transform import Rotation

        from isaaclab_arena_environments.workbench_cleanup.droid_ik import pose_to_matrix

        pose_W_O = self.env.arena_world.get_pose_w(name)[0].numpy()
        pose_W_G = self.pose()[0].numpy()
        T_G_O = np.linalg.inv(pose_to_matrix(pose_W_G[:3], pose_W_G[3:])) @ pose_to_matrix(pose_W_O[:3], pose_W_O[3:])
        T_W_G = pose_to_matrix(t_W_O, q_W_O) @ np.linalg.inv(T_G_O)
        self.move(T_W_G[:3, 3], Rotation.from_matrix(T_W_G[:3, :3]).as_euler("xyz", degrees=True), seconds)

    def pack_tool(self, name, grasp_O, drop_xy, minimum_grasp_z):
        """Attempt a tool transfer from its measured settled pose and require a physical lift."""
        from scipy.spatial.transform import Rotation

        pose_W_O = self.env.arena_world.get_pose_w(name)[0].numpy()
        R_W_O = Rotation.from_quat(pose_W_O[3:])
        t_W_G = pose_W_O[:3] + R_W_O.apply(grasp_O)
        t_W_G[0] += 0.014
        t_W_G[2] = max(t_W_G[2] + 0.021, minimum_grasp_z)
        euler = [0, 45, float(R_W_O.as_euler("xyz", degrees=True)[2] + 180)]
        self.gripper(0, 120)
        self.joint_move([0.24, -0.04, 0.88], [0, 45, 180], 4, canonical_seed=True)
        self.joint_move([t_W_G[0], t_W_G[1], 0.76], euler, 4, canonical_seed=True)
        self.move(t_W_G, euler)
        self.gripper(1, 240)
        self.move([t_W_G[0], t_W_G[1], 0.85], euler, 4)
        assert self.env.arena_world.get_position_w(name)[0, 2] > 0.74, f"The {name} grasp did not lift the tool."
        self.joint_move([0.24, -0.04, 0.88], [0, 45, 180], 4, canonical_seed=True)
        t_W_bin = self.env.arena_world.get_position_w("overhead_bin")[0].numpy().copy()
        t_W_drop = [float(t_W_bin[0] + drop_xy[0]), float(t_W_bin[1] + drop_xy[1]), 0.87]
        self.joint_move(t_W_drop, [0, 45, 180], 4, canonical_seed=True)
        t_W_drop[2] = 0.84
        self.move(t_W_drop, [0, 45, 180], 2)
        self.gripper(0)
        self.move([t_W_drop[0] + 0.14, t_W_drop[1], 0.93], [0, 45, 180])

    def task_two(self):
        with self.subtask(0, "Bring the overhead bin to the table"):
            self.gripper(0.5)
            self.move([0.25, 0.34, 1.325], [90, 0, 180], 4)
            self.move([0.066, 0.34, 1.325], [90, 0, 180], 4)
            self.gripper(1)
            self.move([0.066, 0.34, 1.52], [90, 0, 180], 5)
            self.move([0.40, 0.34, 1.52], [90, 0, 180], 5)
            assert self.env.arena_world.get_position_w("overhead_bin")[0, 2] > 1.25, "The bin grasp slipped."
            self.move_grasped_object("overhead_bin", [0.30, 0.34, 1.32], [0, 0, 0, 1])
            self.move_grasped_object("overhead_bin", [0.30, 0.34, 1.0], [0, 0, 0, 1], 5)
            self.move_grasped_object("overhead_bin", [0.0, 0.24, 0.90], [0, 0, 0, 1], 5)
            self.move_grasped_object("overhead_bin", [0.0, 0.24, 0.675], [0, 0, 0, 1], 5)
            self.gripper(0, 120)
            self.joint_move([0.24, -0.04, 0.88], [0, 45, 180], 4, canonical_seed=True)
        tools = [
            ("slotted_screwdriver", [-0.02, 0, 0.016], [-0.05, -0.04], 0.707),
            ("torx_screwdriver", [-0.02, 0, 0.013], [-0.035, 0.015], 0.700),
            ("phillips_screwdriver", [-0.02, 0, 0.016], [-0.05, 0.045], 0.707),
            ("combination_wrench", [0, 0, 0.009], [0.0, -0.015], 0.696),
            ("small_wrench", [0, 0, 0.007], [0.015, 0.015], 0.694),
        ]
        for index, (name, grasp_O, drop_xy, minimum_z) in enumerate(tools, 1):
            with self.subtask(index, "Place " + name.replace("_", " ") + " in the bin"):
                self.pack_tool(name, grasp_O, drop_xy, minimum_z)
        with self.subtask(6, "Return the loaded bin to the rack"):
            t_W_bin = self.env.arena_world.get_position_w("overhead_bin")[0].numpy().copy()
            self.joint_move([t_W_bin[0] + 0.30, t_W_bin[1], t_W_bin[2] + 0.122], [90, 0, 180], 4)
            self.gripper(0.5, 120)
            self.move([t_W_bin[0] + 0.146, t_W_bin[1], t_W_bin[2] + 0.122], [90, 0, 180], 4)
            self.gripper(1)
            self.move_grasped_object("overhead_bin", [0.30, 0.24, 0.90], [0, 0, 0, 1], 5)
            self.move_grasped_object("overhead_bin", [0.30, 0.34, 1.35], [0, 0, 0, 1], 5)
            self.move_grasped_object("overhead_bin", [-0.08, 0.34, 1.35], [0, 0, 0, 1], 5)
            self.move_grasped_object("overhead_bin", [-0.08, 0.34, 1.205], [0, 0, 0, 1], 5)
            self.gripper(0)
            self.move([0.40, 0.34, 1.40], [90, 0, 180], 4)

    def task_three(self):
        with self.subtask(0, "Turn off the oscilloscope"):
            self.move([0.20, -0.643, 0.86], [0, 50, 180], 4)
            self.gripper(1, 120)
            self.move([0.04, -0.643, 0.710], [0, 50, 180])
            self.move([0.018, -0.643, 0.696], [0, 50, 180], 2)
        with self.subtask(1, "Grasp, withdraw, and release the power plug"):
            self.move([0.20, -0.70, 1.04], [-90, 0, 180], 4)
            self.gripper(0.64, 120)
            self.move([0.04, -0.70, 0.888], [-90, 0, 180])
            self.move([-0.132, -0.70, 0.888], [-90, 0, 180])
            self.gripper(1)
            self.move([0.04, -0.70, 0.888], [-90, 0, 180], 4)
            self.gripper(0.64, 300)
            self.step(300)
        if not self._ViewHelpers._criterion_status(self)["subtask_0/press_button"][0][0]:
            # Unplugging can nudge the free-standing instrument and release its passive button.
            # Reacquire the shifted instrument and press it physically again.
            from scipy.spatial.transform import Rotation

            T_W_S = self.env.arena_world.get_pose_w("oscilloscope")[0].numpy()
            R_W_S = Rotation.from_quat(T_W_S[3:])
            t_W_G = T_W_S[:3] + R_W_S.apply([0.055, -0.143, 0.027])
            euler = [0, 50, 180 + R_W_S.as_euler("xyz", degrees=True)[2]]
            self.mark(0, "recheck_start", "Restore the shifted power button")
            self.move([t_W_G[0] + 0.18, t_W_G[1], 0.86], euler, 4)
            self.gripper(1, 120)
            self.move([t_W_G[0] + 0.025, t_W_G[1], t_W_G[2] + 0.014], euler)
            self.move(t_W_G, euler)
            self.move([t_W_G[0] + 0.10, t_W_G[1], t_W_G[2] + 0.10], euler)
            self.step(600)
            self.mark(0, "recheck_end", "Release the power button and settle the plug")

    def run(self, started):
        from isaaclab_arena.tasks.terminations import task_success_from_progress

        success = False
        error = None
        try:
            self.step(180)
            self.reachability = self.audit_reachability()
            if self.args.audit_only:
                return
            {1: self.task_one, 2: self.task_two, 3: self.task_three}[self.args.task]()
            for _ in range(600):
                if task_success_from_progress(self.env).all().item():
                    break
                self.step()
            success = bool(task_success_from_progress(self.env).all().item())
            assert success, "Arena's required final conditions were not satisfied."
        except Exception as exception:
            error = str(exception)
            raise
        finally:
            report = {
                "task": self.args.task,
                "success": None if self.args.audit_only else success,
                "error": error,
                "audit_only": self.args.audit_only,
                "reachability": getattr(self, "reachability", []),
                "control": "USD-based bounded IK, robot joint-position actions, physical finger contacts",
                "physics_backend": "physx",
                "placement_seed": 17,
                "robot_self_collisions_enabled": self.robot.cfg.spawn.articulation_props.enabled_self_collisions,
                "object_joint_positions": {
                    name: dict(
                        zip(self.env.scene[name].joint_names, self.env.scene[name].data.joint_pos.torch[0].tolist())
                    )
                    for name in ("socket_set", "left_drawers", "oscilloscope")
                },
                "object_pose_writes_during_episode": 0,
                "external_object_wrenches": 0,
                "simulation_time_s": self.steps * self.env.physics_dt,
                "wall_time_s": time.monotonic() - started,
                "subtask_completion": self.env.progress_tracker.get_subtask_completion()[0].tolist(),
                "current_criteria": self._ViewHelpers._criterion_status(self),
                "events": self.events,
                "motions": self.motions,
            }
            (self.out / "report.json").write_text(json.dumps(report, indent=2))
            print("RESULT", json.dumps(report), flush=True)
            if self.writer is not None:
                self.writer.close()


if __name__ == "__main__":
    main()
