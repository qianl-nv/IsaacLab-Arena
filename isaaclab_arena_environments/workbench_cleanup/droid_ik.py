# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded CPU IK for the DROID workbench demonstrations, using the spawned USD joints."""

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def pose_to_matrix(t_A_B, q_A_B):
    """Return the column-vector transform T_A_B for an xyzw pose."""
    T_A_B = np.eye(4)
    T_A_B[:3, :3] = Rotation.from_quat(q_A_B).as_matrix()
    T_A_B[:3, 3] = t_A_B
    return T_A_B


class DroidWorkbenchIK:
    """Fit the seven arm joints while respecting their authored position limits.

    This is a local IK solver, not a collision-aware motion planner. The demo checks
    measured tracking and task predicates in PhysX; an IK solution alone is not a
    manipulation-feasibility result. No cuRobo installation is required.
    """

    def __init__(self, stage, robot_prim_path, T_W_B):
        from pxr import Usd, UsdPhysics

        joint_names = [f"panda_joint{i}" for i in range(1, 9)] + ["panda_hand_joint"]
        joints = {}
        for prim in Usd.PrimRange(stage.GetPrimAtPath(robot_prim_path)):
            if prim.IsA(UsdPhysics.Joint) and prim.GetName() in joint_names:
                joints[prim.GetName()] = prim
        assert set(joint_names) <= set(joints), "The DROID USD arm chain is incomplete."
        self.T_W_B = T_W_B
        self.T_P_J = []
        self.T_J_C = []
        self.axes = []
        limits = []
        for name in joint_names:
            prim = joints[name]
            joint = UsdPhysics.Joint(prim)
            frames = []
            for index in (0, 1):
                t_L_J = getattr(joint, f"GetLocalPos{index}Attr")().Get()
                rotation = getattr(joint, f"GetLocalRot{index}Attr")().Get()
                q_L_J = [*rotation.GetImaginary(), rotation.GetReal()]
                frames.append(pose_to_matrix(t_L_J, q_L_J))
            self.T_P_J.append(frames[0])
            self.T_J_C.append(np.linalg.inv(frames[1]))
            if prim.IsA(UsdPhysics.RevoluteJoint):
                revolute = UsdPhysics.RevoluteJoint(prim)
                self.axes.append(revolute.GetAxisAttr().Get().lower())
                limits.append([revolute.GetLowerLimitAttr().Get(), revolute.GetUpperLimitAttr().Get()])
        limits = np.radians(limits)
        self.lower = limits[:, 0] + 0.001
        self.upper = limits[:, 1] - 0.001
        self.T_E_G = np.eye(4)
        # E: Robotiq base_link; G: nominal midpoint of the open finger pads.
        self.T_E_G[0, 3] = 0.131
        self.preferred_joints = np.array([0.0, -0.6, 0.0, -2.2, 0.0, 2.0, 0.0])

    def forward(self, joint_positions):
        """Return T_W_G for seven arm angles in radians."""
        T_W_L = self.T_W_B.copy()
        for index, (T_P_J, T_J_C) in enumerate(zip(self.T_P_J, self.T_J_C)):
            T_W_L = T_W_L @ T_P_J
            if index < 7:
                T_J_Jm = np.eye(4)
                T_J_Jm[:3, :3] = Rotation.from_euler(self.axes[index], joint_positions[index]).as_matrix()
                T_W_L = T_W_L @ T_J_Jm
            T_W_L = T_W_L @ T_J_C
        return T_W_L @ self.T_E_G

    def solve(self, t_W_G, q_W_G, seed, multistart=False):
        """Return arm angles, position error in meters, and rotation error in radians.

        Args:
            t_W_G: Requested finger-pad midpoint in world coordinates.
            q_W_G: Requested gripper orientation, xyzw.
            seed: Seven starting joint angles.
            multistart: Try deterministic extra seeds for an isolated reachability query.

        Returns:
            Joint angles and the two residual norms. Callers must check these residuals.
        """
        R_W_G = Rotation.from_quat(q_W_G).as_matrix()
        seed = np.clip(seed, self.lower + 0.0001, self.upper - 0.0001)

        def residual(joint_positions):
            T_W_actual = self.forward(joint_positions)
            error_W = Rotation.from_matrix(R_W_G @ T_W_actual[:3, :3].T).as_rotvec()
            return np.r_[
                T_W_actual[:3, 3] - t_W_G,
                0.25 * error_W,
                0.003 * (joint_positions - self.preferred_joints),
            ]

        seeds = [seed]
        if multistart:
            rng = np.random.default_rng(7)
            seeds.extend(rng.uniform(self.lower, self.upper) for _ in range(16))
        best_error = float("inf")
        best_joints = seed.copy()
        for candidate in seeds:
            fit = least_squares(
                residual,
                candidate,
                bounds=(self.lower, self.upper),
                max_nfev=150,
                ftol=1e-7,
                xtol=1e-7,
                gtol=1e-7,
            )
            error = np.linalg.norm(residual(fit.x)[:6])
            if error < best_error:
                best_error, best_joints = error, fit.x
            if best_error < 0.0005:
                break
        # Refine the pose after choosing a posture away from the joint limits.
        preferred = best_joints.copy()

        def precise_residual(joint_positions):
            T_W_actual = self.forward(joint_positions)
            error_W = Rotation.from_matrix(R_W_G @ T_W_actual[:3, :3].T).as_rotvec()
            return np.r_[T_W_actual[:3, 3] - t_W_G, 0.25 * error_W, 0.0001 * (joint_positions - preferred)]

        fit = least_squares(
            precise_residual,
            best_joints,
            bounds=(self.lower, self.upper),
            max_nfev=60,
            gtol=1e-7,
        )
        best_joints = fit.x
        T_W_actual = self.forward(best_joints)
        position_error = np.linalg.norm(T_W_actual[:3, 3] - t_W_G)
        rotation_error = np.linalg.norm(Rotation.from_matrix(R_W_G @ T_W_actual[:3, :3].T).as_rotvec())
        return best_joints, float(position_error), float(rotation_error)
