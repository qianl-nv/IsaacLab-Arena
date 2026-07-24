# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

import torch

import warp as wp
from isaaclab.envs import ManagerBasedEnv
from isaaclab.managers import SceneEntityCfg

from isaaclab_arena.utils.pose import Pose
from isaaclab_arena.utils.velocity import Velocity

SceneWritePoseSpecs = list[tuple[str, Pose]]
PerEnvSceneWritePoseSpecs = list[SceneWritePoseSpecs]


def set_object_pose(
    env: ManagerBasedEnv,
    env_ids: torch.Tensor,
    asset_cfg: SceneEntityCfg,
    pose: Pose,
    velocity: Velocity | None = None,
) -> None:
    if env_ids is None:
        return
    # Grab the object
    asset = env.scene[asset_cfg.name]
    num_envs = len(env_ids)
    # Convert the pose to the env frame
    pose_t_xyz_q_xyzw = pose.to_tensor(device=env.device).repeat(num_envs, 1)
    pose_t_xyz_q_xyzw[:, :3] += env.scene.env_origins[env_ids]
    # Set the pose and velocity
    asset.write_root_pose_to_sim(pose_t_xyz_q_xyzw, env_ids=env_ids)
    if velocity is not None:
        vel = velocity.to_tensor(device=env.device).unsqueeze(0).expand(num_envs, -1)
        asset.write_root_velocity_to_sim(vel, env_ids=env_ids)
    else:
        asset.write_root_velocity_to_sim(torch.zeros(num_envs, 6, device=env.device), env_ids=env_ids)


def write_scene_asset_pose_at_env(
    env: ManagerBasedEnv,
    env_id: int,
    scene_name: str,
    pose: Pose,
) -> None:
    """Write one scene asset root pose for a single environment index."""
    scene_asset = env.scene[scene_name]
    env_id_tensor = torch.tensor([env_id], device=env.device)
    pose_tensor = pose.to_tensor(device=env.device).unsqueeze(0)
    pose_tensor[0, :3] += env.scene.env_origins[env_id, :]
    if hasattr(scene_asset, "write_root_pose_to_sim"):
        scene_asset.write_root_pose_to_sim(pose_tensor, env_ids=env_id_tensor)
        if hasattr(scene_asset, "write_root_velocity_to_sim"):
            scene_asset.write_root_velocity_to_sim(
                torch.zeros(1, 6, device=env.device),
                env_ids=env_id_tensor,
            )
        return
    if hasattr(scene_asset, "set_world_poses"):
        scene_asset.set_world_poses(
            pose_tensor[:, :3],
            pose_tensor[:, 3:],
            indices=env_id_tensor.cpu(),
        )
        return
    raise TypeError(f"Scene asset '{scene_name}' does not support pose writes.")


def reset_placement_asset_pose(
    env: ManagerBasedEnv,
    env_ids: torch.Tensor,
    write_pose_specs: SceneWritePoseSpecs,
) -> None:
    """Reset one fixed layout pose across all requested environments."""
    if env_ids is None:
        return
    for cur_env in env_ids.tolist():
        for scene_name, pose in write_pose_specs:
            write_scene_asset_pose_at_env(env, cur_env, scene_name, pose)


def reset_placement_asset_pose_per_env(
    env: ManagerBasedEnv,
    env_ids: torch.Tensor,
    write_pose_list: PerEnvSceneWritePoseSpecs,
) -> None:
    """Reset per-environment layout poses for one placement asset."""
    if env_ids is None:
        return
    for cur_env in env_ids.tolist():
        for scene_name, pose in write_pose_list[cur_env]:
            write_scene_asset_pose_at_env(env, cur_env, scene_name, pose)


def set_object_pose_per_env(
    env: ManagerBasedEnv,
    env_ids: torch.Tensor,
    asset_cfg: SceneEntityCfg,
    pose_list: list[Pose],
) -> None:
    if env_ids is None:
        return

    # Grab the object
    asset = env.scene[asset_cfg.name]

    # Set the objects pose in each environment independently
    assert env_ids.ndim == 1
    for cur_env in env_ids.tolist():
        # Convert the pose to the env frame
        pose = pose_list[cur_env]
        pose_t_xyz_q_xyzw = pose.to_tensor(device=env.device).unsqueeze(0)
        pose_t_xyz_q_xyzw[0, :3] += env.scene.env_origins[cur_env, :]
        # Set the pose and velocity
        asset.write_root_pose_to_sim(pose_t_xyz_q_xyzw, env_ids=torch.tensor([cur_env], device=env.device))
        asset.write_root_velocity_to_sim(
            torch.zeros(1, 6, device=env.device), env_ids=torch.tensor([cur_env], device=env.device)
        )


def reset_all_articulation_joints(env: ManagerBasedEnv, env_ids: torch.Tensor):
    """Reset the articulation joints to the initial state."""
    for articulation_asset in env.scene.articulations.values():
        # obtain default and deal with the offset for env origins
        default_root_state = wp.to_torch(articulation_asset.data.default_root_state)[env_ids].clone()
        default_root_state[:, 0:3] += env.scene.env_origins[env_ids]
        # set into the physics simulation
        articulation_asset.write_root_pose_to_sim(default_root_state[:, :7], env_ids=env_ids)
        articulation_asset.write_root_velocity_to_sim(default_root_state[:, 7:], env_ids=env_ids)
        # obtain default joint positions
        default_joint_pos = wp.to_torch(articulation_asset.data.default_joint_pos)[env_ids].clone()
        default_joint_vel = wp.to_torch(articulation_asset.data.default_joint_vel)[env_ids].clone()
        # set into the physics simulation
        articulation_asset.write_joint_state_to_sim(default_joint_pos, default_joint_vel, env_ids=env_ids)
