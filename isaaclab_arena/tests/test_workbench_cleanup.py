# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Reject incomplete case storage and invalid plug withdrawal states."""

from isaaclab_arena.tests.utils.persistent_simulation_app import run_function_with_persistent_simulation_app


def _test_workbench_completion_boundaries(_simulation_app):
    import torch
    from types import SimpleNamespace

    from isaaclab_arena.utils.bounding_box import AxisAlignedBoundingBox
    from isaaclab_arena_environments.workbench_cleanup.tasks import (
        ClosedCaseInDrawerTask,
        ToolInBinTask,
        plug_seated,
        plug_withdrawn,
    )

    poses = {
        "outlet": torch.tensor([[0, 0, 0, 0, 0, 0, 1.0]]).repeat(4, 1),
        "plug": torch.tensor([
            [0.055, 0, 0.03, 0, 0, 0, 1],
            [0.055, 0.1, 0.03, 0, 0, 0, 1],
            [0.2, 0, 0.03, 0, 0, 0, 1],
            [0.2, 0, 0.03, 0, 0, 0, 1],
        ]),
    }
    speeds_W = torch.zeros(4, 3)
    speeds_W[3, 0] = 0.1
    world = SimpleNamespace(
        get_pose_w=poses.__getitem__,
        get_root_linear_velocity_w=lambda name: speeds_W,
        get_root_angular_velocity_w=lambda name: torch.zeros(4, 3),
    )
    env = SimpleNamespace(num_envs=4, device="cpu", arena_world=world)
    assert plug_seated(env, "plug", "outlet").tolist() == [True, False, False, False]
    assert plug_withdrawn(env, "plug", "outlet", 0.12).tolist() == [False, False, True, False]

    poses["case"] = torch.tensor([
        [0, 0, 0, 0, 0, 0, 1],
        [0.3, 0, 0, 0, 0, 0, 1],
        [0, 0, 0, 0, 0, 0, 1],
        [0, 0, 0, 0, 0, 0.70710678, 0.70710678],
    ])
    world.get_aabb_w = lambda name: AxisAlignedBoundingBox((-0.25, -0.1, -0.1), (0.25, 0.1, 0.1))
    case = SimpleNamespace(
        name="case",
        get_bounding_box=lambda: AxisAlignedBoundingBox((-0.2, -0.05, -0.025), (0.2, 0.05, 0.025)),
        is_closed=lambda env, threshold: torch.tensor([True, True, False, True]),
    )
    task = ClosedCaseInDrawerTask.__new__(ClosedCaseInDrawerTask)
    task.object = case
    task.target = SimpleNamespace(name="drawer")
    task.minimum_contained_fraction = 0.98
    assert task._contained(env).tolist() == [True, False, False, False]

    env.num_envs = 2
    poses["tool"] = torch.tensor([
        [0, 0, 0.2, 0, 0.38268343, 0, 0.92387953],
        [0, 0, 0.17, 0, 0.38268343, 0, 0.92387953],
    ])
    world.get_aabb_w = lambda name: AxisAlignedBoundingBox((-0.3, -0.1, 0.075), (0.3, 0.1, 0.4))
    tool_task = ToolInBinTask.__new__(ToolInBinTask)
    tool_task.object = SimpleNamespace(
        name="tool",
        hull_vertices_O=[[-0.2, -0.005, 0], [-0.2, 0.005, 0], [0.2, -0.005, 0.04], [0.2, 0.005, 0.04]],
    )
    tool_task.target = SimpleNamespace(name="bin")
    tool_task.minimum_contained_fraction = 1.0
    assert tool_task._contained(env).tolist() == [True, False]
    enclosing_box = AxisAlignedBoundingBox((-0.2, -0.005, 0), (0.2, 0.005, 0.04))
    rotated_box = enclosing_box.transformed(poses["tool"][:, :3], poses["tool"][:, 3:]).to_aabb()
    assert rotated_box.min_point[0, 2] < 0.075
    return True


def test_workbench_completion_boundaries():
    assert run_function_with_persistent_simulation_app(_test_workbench_completion_boundaries)
