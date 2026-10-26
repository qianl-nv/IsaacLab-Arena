# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Inspect the workbench with mouse forces or replay bounded force-controlled demonstrations."""

import argparse
import json
from pathlib import Path

from isaaclab.app import AppLauncher

from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    AppLauncher.add_app_launcher_args(parser)
    parser.add_argument("--task", type=int, choices=[1, 2, 3], default=1)
    parser.add_argument("--output", type=Path, default=Path("artifacts/workbench_cleanup"))
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--commands", type=Path, help="Read live force-teleoperation commands from a JSONL file.")
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--inspect", action="store_true")
    parser.set_defaults(device="cpu", visualizer=["kit"])
    args = parser.parse_args()
    with SimulationAppContext(args):
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
        from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
        from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

        spec = ArenaEnvGraphSpec.from_yaml(Path(__file__).with_name(f"task_{args.task}.yaml"))
        arena = spec.to_arena_env()
        builder = ArenaEnvBuilder(
            arena,
            ArenaEnvBuilderCfg(
                device="cpu",
                num_envs=1,
                disable_fabric=False,
                placement_seed=17,
            ),
        )
        cfg, kwargs = builder.build_env_cfg()
        from isaaclab.actuators import ImplicitActuatorCfg

        for name, joint_name in {
            "socket_set": "case_lid",
            "left_drawers": "joint_drawersA_01_joint_00",
            "oscilloscope": "joint_button_01_joint_00",
        }.items():
            getattr(cfg.scene, name).actuators = {
                "force_operator": ImplicitActuatorCfg(
                    joint_names_expr=[joint_name], stiffness=0.0, damping=0.0, effort_limit_sim=100.0
                ),
            }
        cfg.sim.enable_scene_query_support = True
        env = builder.make_registered(cfg, kwargs)
        try:
            env.reset()
            demo = ForceDemo(env.unwrapped, args)
            demo.run()
        finally:
            env.close()


class ForceDemo:
    """Drive physical wrenches and joint efforts, and evaluate Arena's real task predicates."""

    def __init__(self, env, args):
        import torch

        self.env = env
        self.args = args
        self.torch = torch
        self.out = args.output / f"task_{args.task}"
        self.out.mkdir(parents=True, exist_ok=True)
        self.steps = 0
        self.holds = {}
        self.joint_holds = {}
        self.frames = 0
        self.writer = None
        self.rgb = None
        self.events = []
        self.stage = None
        self.viewport = None
        self.last_image = None
        if not args.no_record:
            import imageio.v2 as imageio
            import omni.usd
            from omni.kit.viewport.utility import get_active_viewport

            self.stage = omni.usd.get_context().get_stage()
            self.viewport = get_active_viewport()
            self.viewport.resolution = (960, 720)
            self.env.sim.set_camera_view(eye=[2.15, -1.8, 1.8], target=[0, 0, 0.76])
            self.writer = imageio.get_writer(str(self.out / "demo.mp4"), fps=20, codec="libx264", quality=8)
            for _ in range(30):
                self.env.sim.render()
        self._add_cable()

    def _capture_frame(self):
        import ctypes
        import numpy as np

        from omni.kit.viewport.utility import capture_viewport_to_buffer

        captured = []

        def receive(buffer, buffer_size, width, height, byte_format):
            get_pointer = ctypes.pythonapi.PyCapsule_GetPointer
            get_pointer.restype = ctypes.c_void_p
            get_pointer.argtypes = [ctypes.py_object, ctypes.c_char_p]
            pointer = ctypes.cast(get_pointer(buffer, None), ctypes.POINTER(ctypes.c_uint8))
            pixels = np.ctypeslib.as_array(pointer, shape=(buffer_size,))
            captured.append(pixels.reshape(height, width, 4)[:, :, :3].copy())

        capture_viewport_to_buffer(self.viewport, receive)
        for _ in range(30):
            self.env.sim.render()
            if captured:
                self.last_image = captured[0]
                self.writer.append_data(self.last_image)
                self.frames += 1
                return
        raise RuntimeError("Viewport capture did not return an image.")

    def _add_cable(self):
        """Draw the lead between the fixed device and the independently simulated plug."""
        import omni.usd
        from pxr import UsdGeom

        self.stage = omni.usd.get_context().get_stage()
        self.cable = UsdGeom.BasisCurves.Define(self.stage, "/World/envs/env_0/workbench/PowerLead")
        self.cable.CreateTypeAttr("linear")
        self.cable.CreateCurveVertexCountsAttr([6])
        self.cable.CreateWidthsAttr([0.006] * 6)
        self.cable.CreateDisplayColorAttr([(0.025, 0.025, 0.025)])
        self._update_cable()

    def _update_cable(self):
        from pxr import Gf

        t_W_P = self.env.arena_world.get_position_w("power_plug")[0].tolist()
        t_W_D = self.env.arena_world.get_position_w("oscilloscope")[0].tolist()
        points = [
            (t_W_D[0] - 0.07, t_W_D[1], t_W_D[2] + 0.05),
            (-0.15, -0.48, 0.685),
            (-0.12, -0.56, 0.68),
            (0.0, -0.62, 0.70),
            (t_W_P[0] + 0.05, t_W_P[1], t_W_P[2] - 0.02),
            tuple(t_W_P),
        ]
        self.cable.GetPointsAttr().Set([Gf.Vec3f(*point) for point in points])

    def _update_power_display(self):
        """Show the button-defined off state on the source oscilloscope screen."""
        from pxr import Sdf, UsdGeom, UsdShade

        pressed = self.env.cfg.task_progress.success_criteria[0].predicate_sequence[0](self.env)
        powered_off = pressed[0].item()
        if powered_off == getattr(self, "display_is_off", False):
            return
        if not hasattr(self, "screen_bindings"):
            self.screen_bindings = []
            for prim in self.stage.Traverse():
                if (
                    prim.IsA(UsdGeom.Subset)
                    and "body_01_obj_00" in str(prim.GetPath())
                    and prim.GetName() == "m_opaque__paper__oscilloscope_a01"
                ):
                    binding = UsdShade.MaterialBindingAPI(prim)
                    self.screen_bindings.append((binding, binding.GetDirectBindingRel().GetTargets()))
            assert self.screen_bindings, "The oscilloscope screen material subset was not found."
        material = UsdShade.Material.Define(self.stage, "/World/OscilloscopeDisplayOff")
        shader = UsdShade.Shader.Define(self.stage, "/World/OscilloscopeDisplayOff/Shader")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set((0.005, 0.009, 0.012))
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.3)
        material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        for binding, on_material in self.screen_bindings:
            if powered_off:
                binding.Bind(material)
            else:
                binding.GetDirectBindingRel().SetTargets(on_material)
        self.display_is_off = powered_off

    def _apply_forces(self):
        from isaaclab.utils.math import compute_pose_error

        torch = self.torch
        for name, (t_W_goal, q_W_goal) in self.holds.items():
            obj = self.env.scene[name]
            T_W_O = self.env.arena_world.get_pose_w(name)
            v_W = self.env.arena_world.get_root_linear_velocity_w(name)
            omega_W = self.env.arena_world.get_root_angular_velocity_w(name)
            _, error_W = compute_pose_error(T_W_O[:, :3], T_W_O[:, 3:], t_W_goal, q_W_goal)
            masses = obj.data.body_mass.torch
            mass = masses.sum().item()
            acceleration_W = 150 * (t_W_goal - T_W_O[:, :3]) - 24 * v_W
            if name != "power_plug":
                acceleration_W[:, 2] += 9.81
            force_W = (mass * acceleration_W).clamp(-100, 100)
            if "screwdriver" in name or "wrench" in name:
                # Pull a light tool out from under heavier tools in the clutter pile.
                stiffness = max(150 * mass, 60)
                damping = 2 * (stiffness * mass) ** 0.5
                force_W = stiffness * (t_W_goal - T_W_O[:, :3]) - damping * v_W
                force_W[:, 2] += mass * 9.81
                force_W = force_W.clamp(-100, 100)
            from isaaclab.utils.math import quat_apply, quat_apply_inverse

            q_W_B = T_W_O[:, 3:]
            acceleration_B = quat_apply_inverse(q_W_B, 100 * error_W - 20 * omega_W)
            inertia_B = obj.data.body_inertia.torch.reshape(1, -1, 3, 3).sum(dim=1)
            torque_B = self.torch.bmm(inertia_B, acceleration_B[:, :, None]).squeeze(-1)
            torque_W = quat_apply(q_W_B, torque_B).clamp(-5, 5)
            if name == "socket_set":
                torque_W = (2 * error_W - 0.2 * omega_W).clamp(-2, 2)
            elif name == "overhead_bin":
                torque_W = (6 * error_W - 0.6 * omega_W).clamp(-5, 5)
            if not hasattr(self, "last_wrenches"):
                self.last_wrenches = {}
            self.last_wrenches[name] = {
                "goal": t_W_goal.tolist(),
                "velocity": v_W.tolist(),
                "force": force_W.tolist(),
                "mass": mass,
            }
            forces_W = masses[:, :, None] / mass * force_W[:, None, :]
            torques_W = torch.zeros_like(forces_W)
            torques_W[:, 0, :] = torque_W
            obj.permanent_wrench_composer.set_forces_and_torques_index(
                forces=forces_W,
                torques=torques_W,
                is_global=True,
            )
        for (name, joint_name), (goal, gain, damping, limit) in self.joint_holds.items():
            obj = self.env.scene[name]
            joint_id = obj.data.joint_names.index(joint_name)
            q = obj.data.joint_pos.torch[:, joint_id]
            qd = obj.data.joint_vel.torch[:, joint_id]
            effort = (gain * (goal - q) - damping * qd).clamp(-limit, limit)
            obj.set_joint_effort_target(effort[:, None], joint_ids=[joint_id])

    def step(self, count=1):
        for _ in range(count):
            self._apply_forces()
            self.env.scene.write_data_to_sim()
            self.env.sim.step(render=False)
            self.env.scene.update(self.env.physics_dt)
            self.steps += 1
            if self.steps % self.env.cfg.decimation == 0:
                self.env.common_step_counter += 1
                self.env.episode_length_buf += 1
                self.env.update_task_progress()
            if self.steps % 6 == 0:
                if self.args.task == 3:
                    self._update_cable()
                    self._update_power_display()
                if self.viewport is not None:
                    self._capture_frame()

    def mark(self, index, boundary, title):
        import imageio.v3 as iio

        if self.viewport is not None:
            self._capture_frame()
        record = {
            "subtask": index,
            "boundary": boundary,
            "title": title,
            "simulation_time_s": self.steps * self.env.physics_dt,
            "completion": self.env.progress_tracker.get_subtask_completion()[0].tolist(),
        }
        if self.last_image is not None:
            filename = f"{index:02d}_{boundary}.png"
            iio.imwrite(self.out / filename, self.last_image)
            record["viewport"] = filename
        self.events.append(record)
        print("SUBTASK", json.dumps(record), flush=True)
        (self.out / "progress.json").write_text(json.dumps(self.events, indent=2))

    def move(self, name, goal, seconds=2.0, orientation=None):
        torch = self.torch
        T_W_start = self.env.arena_world.get_pose_w(name).clone()
        t_W_goal = torch.tensor([goal], dtype=torch.float32)
        if orientation is None:
            q_W_goal = self.holds[name][1] if name in self.holds else T_W_start[:, 3:]
        else:
            q_W_goal = torch.tensor([orientation], dtype=torch.float32)
        count = int(seconds / self.env.physics_dt)
        for i in range(count):
            alpha = (i + 1) / count
            alpha = alpha * alpha * (3 - 2 * alpha)
            self.holds[name] = ((1 - alpha) * T_W_start[:, :3] + alpha * t_W_goal, q_W_goal)
            self.step()
        self.step(60)
        print("MOVE_RESULT", name, self.env.arena_world.get_pose_w(name).tolist(), flush=True)

    def release(self, name):
        self.holds.pop(name, None)
        self.env.scene[name].permanent_wrench_composer.reset()

    def lift(self, name, height, seconds=3.0):
        """Raise an object with a physical wrench while preserving its horizontal goal."""
        t_W = self.env.arena_world.get_position_w(name)[0].tolist()
        self.move(name, [t_W[0], t_W[1], height], seconds=seconds)

    def joint(self, name, joint_name, goal, seconds=2.0, gain=40, damping=6, limit=30):
        obj = self.env.scene[name]
        joint_id = obj.data.joint_names.index(joint_name)
        start = obj.data.joint_pos.torch[0, joint_id].item()
        count = int(seconds / self.env.physics_dt)
        for i in range(count):
            alpha = (i + 1) / count
            self.joint_holds[(name, joint_name)] = (start + alpha * (goal - start), gain, damping, limit)
            self.step()
        self.step(90)

    def require(self, index):
        for _ in range(600):
            if self.env.progress_tracker.get_subtask_completion()[0, index].item():
                return
            self.step()
        states = self.env.progress_tracker.get_subtask_completion()[0].tolist()
        raise AssertionError(f"Subtask {index} did not complete: {states}")

    def wait_for_final(self):
        """Allow the required final conditions to settle after the last movement."""
        from isaaclab_arena.tasks.terminations import task_success_from_progress

        for _ in range(1200):
            if task_success_from_progress(self.env).all().item():
                return
            self.step()

    def _criterion_status(self):
        status = {}
        for criterion in self.env.cfg.task_progress.success_criteria:
            values = []
            for predicate in criterion.predicate_sequence:
                evaluate = getattr(predicate, "predicate", predicate)
                values.append(evaluate(self.env).tolist())
            status[criterion.name] = values
        return status

    def run(self):
        try:
            self.step(240)
            print(
                "INITIAL_POSES",
                {
                    n: self.env.arena_world.get_pose_w(n).tolist()
                    for n in [
                        "socket_set",
                        "oscilloscope",
                        "overhead_bin",
                        "top_left_drawer",
                        "power_plug",
                        "outlet",
                        "slotted_screwdriver",
                        "torx_screwdriver",
                        "phillips_screwdriver",
                        "combination_wrench",
                        "small_wrench",
                    ]
                },
                flush=True,
            )
            print("JOINTS", {n: o.data.joint_names for n, o in self.env.scene.articulations.items()}, flush=True)
            if self.args.inspect:
                self.mark(0, "start", "Scene inspection")
                return
            if self.args.commands is not None:
                self.command_teleoperation()
            elif self.args.interactive:
                self.interactive()
            elif self.args.task == 1:
                self.task_one()
            elif self.args.task == 2:
                self.task_two()
            else:
                self.task_three()
            from isaaclab_arena.tasks.terminations import task_success_from_progress

            self.wait_for_final()
            if self.events and self.events[-1]["boundary"] == "end":
                last = self.events.pop()
                self.mark(last["subtask"], "end", last["title"])
            success = task_success_from_progress(self.env).tolist()
            report = {
                "mode": (
                    "command_force_teleoperation"
                    if self.args.commands is not None
                    else "mouse_teleoperation" if self.args.interactive else "scripted_physics_forces"
                ),
                "success": success,
                "subtasks": self.env.progress_tracker.get_subtask_completion().tolist(),
                "current_predicates": self._criterion_status(),
                "video_frames": self.frames,
                "final_poses": {
                    name: self.env.arena_world.get_pose_w(name).tolist()
                    for name in (*self.env.scene.articulations, *self.env.scene.rigid_objects)
                },
                "final_joints": {
                    name: dict(zip(obj.data.joint_names, obj.data.joint_pos.torch[0].tolist()))
                    for name, obj in self.env.scene.articulations.items()
                },
                "events": self.events,
                "limitations": [
                    "Power lead is visual; plug withdrawal is geometric, without electrical or cable simulation."
                ],
            }
            (self.out / "validation.json").write_text(json.dumps(report, indent=2))
            assert all(success), f"Final task conditions failed: {report}"
            print("TASK_SUCCESS", json.dumps(report), flush=True)
        finally:
            if self.writer is not None:
                self.writer.close()

    def command_teleoperation(self, cursor=0):
        """Execute operator commands as physical forces while recording task predicates."""
        import time

        actions = {
            "move": self.move,
            "lift": self.lift,
            "joint": self.joint,
            "release": self.release,
            "wait": self.step,
            "mark": self.mark,
            "check": self.require,
            "wait_final": self.wait_for_final,
        }
        print("TELEOP_READY", str(self.args.commands), flush=True)
        while True:
            lines = self.args.commands.read_text().splitlines() if self.args.commands.exists() else []
            if cursor == len(lines):
                self.env.sim.render()
                time.sleep(0.05)
                continue
            command = json.loads(lines[cursor])
            cursor += 1
            print("TELEOP_COMMAND", json.dumps(command), flush=True)
            action = command.pop("action")
            if action == "reload_controls":
                import runpy

                self.__class__ = runpy.run_path(__file__, run_name="_workbench_controls")["ForceDemo"]
                self.command_teleoperation(cursor)
                return
            if action == "finish":
                return
            if action == "inspect":
                print(
                    "TELEOP_STATE",
                    {
                        "poses": {
                            name: self.env.arena_world.get_pose_w(name).tolist()
                            for name in ["socket_set", "overhead_bin", "power_plug", "top_left_drawer"]
                        },
                        "joints": {
                            name: obj.data.joint_pos.torch.tolist()
                            for name, obj in self.env.scene.articulations.items()
                        },
                        "completion": self.env.progress_tracker.get_subtask_completion().tolist(),
                        "current_predicates": self._criterion_status(),
                        "velocities": {
                            name: {
                                "linear": self.env.arena_world.get_root_linear_velocity_w(name).norm(dim=-1).tolist(),
                                "angular": self.env.arena_world.get_root_angular_velocity_w(name).norm(dim=-1).tolist(),
                            }
                            for name in self.env.scene.rigid_objects
                        },
                        "contacts": {
                            name: sensor.data.force_matrix_w.torch.norm().item()
                            for name, sensor in self.env.scene.sensors.items()
                            if name.startswith("contact_sensor_")
                        },
                        "wrenches": getattr(self, "last_wrenches", {}),
                        "bodies": {
                            name: {
                                "names": obj.data.body_names,
                                "mass": obj.data.body_mass.torch.tolist(),
                                "fixed": getattr(obj, "is_fixed_base", False),
                                "forces": obj.permanent_wrench_composer.global_force_at_com_w.numpy().tolist(),
                            }
                            for name, obj in self.env.scene.articulations.items()
                        },
                        "native_poses": {
                            name: {
                                "paths": obj.root_view.prim_paths,
                                "poses": (
                                    (
                                        obj.root_view.get_root_transforms()
                                        if name in self.env.scene.articulations
                                        else obj.root_view.get_transforms()
                                    )
                                    .numpy()
                                    .tolist()
                                ),
                            }
                            for name, obj in {**self.env.scene.articulations, **self.env.scene.rigid_objects}.items()
                        },
                    },
                    flush=True,
                )
            else:
                assert action in actions, f"Unknown command: {action}"
                actions[action](**command)
            print("TELEOP_DONE", cursor, flush=True)

    def task_one(self):
        self.mark(0, "start", "Close socket set")
        self.joint("socket_set", "case_lid", 0.0, gain=1, damping=0.06, limit=0.5)
        self.require(0)
        self.mark(0, "end", "Close socket set")
        self.mark(1, "start", "Open top-left drawer")
        self.joint("left_drawers", "joint_drawersA_01_joint_00", 0.245, gain=300, damping=50, limit=70)
        self.require(1)
        self.mark(1, "end", "Open top-left drawer")
        self.mark(2, "start", "Place socket set in drawer")
        t_W = self.env.arena_world.get_position_w("socket_set")[0].tolist()
        self.move("socket_set", [t_W[0], t_W[1], 0.90])
        self.move("socket_set", [0.40, -0.524, 0.90], orientation=[0, 0, 0.70710678, 0.70710678])
        self.move("socket_set", [0.40, -0.524, 0.52], seconds=3)
        self.release("socket_set")
        self.require(2)
        self.mark(2, "end", "Place socket set in drawer")
        self.mark(3, "start", "Close loaded drawer")
        self.joint("left_drawers", "joint_drawersA_01_joint_00", 0.0, seconds=4, gain=300, damping=50, limit=70)
        self.require(3)
        self.step(120)
        self.mark(3, "end", "Close loaded drawer")

    def task_two(self):
        self.mark(0, "start", "Bring overhead bin to table")
        self.move("overhead_bin", [0.30, 0.34, 1.48], orientation=[0, 0, 0, 1])
        self.move("overhead_bin", [0.32, 0.23, 0.85])
        self.move("overhead_bin", [0.0, 0.23, 0.675])
        self.release("overhead_bin")
        self.require(0)
        self.mark(0, "end", "Bring overhead bin to table")
        tools = [
            "slotted_screwdriver",
            "torx_screwdriver",
            "phillips_screwdriver",
            "combination_wrench",
            "small_wrench",
        ]
        for index, name in enumerate(tools, 1):
            self.mark(index, "start", "Put " + name + " in bin")
            t_W = self.env.arena_world.get_position_w(name)[0].tolist()
            self.move(name, [t_W[0], t_W[1], 0.98], seconds=3)
            t_W_bin = self.env.arena_world.get_position_w("overhead_bin")[0].tolist()
            center_O = self.env.arena_world.get_aabb_in_local_frame(name).center[0].tolist()
            target = [
                t_W_bin[0] - center_O[0],
                t_W_bin[1] + [-0.065, -0.03, 0.005, 0.04, 0.075][index - 1] - center_O[1],
                0.88,
            ]
            orientation = [0, 0, 0, 1]
            if name == "small_wrench":
                target = [t_W_bin[0] + 0.11 + center_O[1], t_W_bin[1] - center_O[0], 0.90]
                orientation = [0, 0, 0.70710678, 0.70710678]
            self.move(name, target, orientation=orientation, seconds=3)
            target[2] = [0.705, 0.715, 0.725, 0.73, 0.715][index - 1]
            self.move(name, target, seconds=2)
            self.release(name)
            self.step(240)
            self.require(index)
            self.mark(index, "end", "Put " + name + " in bin")
        self.mark(6, "start", "Return loaded bin to rack")
        self.move("overhead_bin", [0.45, 0.23, 0.95], seconds=4, orientation=[0, 0, 0, 1])
        self.move("overhead_bin", [0.45, 0.23, 1.65], seconds=5)
        self.move("overhead_bin", [-0.08, 0.34, 1.65], seconds=4)
        self.move("overhead_bin", [-0.08, 0.34, 1.208], seconds=3)
        self.release("overhead_bin")
        self.require(6)
        self.step(180)
        self.mark(6, "end", "Return loaded bin to rack")

    def task_three(self):
        self.mark(0, "start", "Switch oscilloscope off")
        self.joint("oscilloscope", "joint_button_01_joint_00", -0.00235, gain=2, damping=0.015, limit=0.01)
        self.require(0)
        self.mark(0, "end", "Switch oscilloscope off")
        self.mark(1, "start", "Withdraw power plug")
        t_W = self.env.arena_world.get_position_w("power_plug")[0].tolist()
        t_W[0] += 0.16
        self.move("power_plug", t_W, orientation=[0, 0, 0, 1])
        self.release("power_plug")
        self.require(1)
        self.mark(1, "end", "Withdraw power plug")

    def interactive(self):
        import omni.kit.app

        from isaaclab_arena.scripts.environment_runner import _enable_mouse_interaction

        _enable_mouse_interaction()
        index = 0
        count = self.env.progress_tracker.get_subtask_completion().shape[1]
        self.mark(index, "start", "Mouse teleoperation")
        while index < count and omni.kit.app.get_app().is_running():
            self.step(6)
            if self.env.progress_tracker.get_subtask_completion()[0, index].item():
                self.mark(index, "end", "Mouse teleoperation")
                index += 1
                if index < count:
                    self.mark(index, "start", "Mouse teleoperation")


if __name__ == "__main__":
    main()
