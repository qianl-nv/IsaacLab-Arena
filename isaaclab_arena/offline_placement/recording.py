# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Shared asset checks and JSONL output for placement recording."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import gymnasium as gym

    from isaaclab.envs import ManagerBasedEnv

    from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
    from isaaclab_arena.offline_placement.post_physics_validation import PlacementOutcome
    from isaaclab_arena.offline_placement.recording_config import PlacementRecordingCfg
    from isaaclab_arena.offline_placement.settled_placement_params import SettledPlacementParams
    from isaaclab_arena.relations.placement_asset import PlaceableAsset
    from isaaclab_arena.utils.pose import Pose


@dataclass
class PlacementRecordingSummary:
    """Recording output and candidate acceptance counts."""

    output: Path | None
    """Written JSONL path, or None when no candidates were accepted."""
    accepted: int
    """Number of candidates that passed all required checks."""
    attempted: int
    """Total sampled candidates, including solver failures."""
    rejections: dict[tuple[int, int], str]
    """Rejection reasons keyed by source (environment index, reset batch index)."""


def collect_layouts_until_count(
    env: ManagerBasedEnv,
    min_layouts: int,
    max_batches: int,
    params: SettledPlacementParams | None = None,
    *,
    render: bool = False,
    scene_assets: list[PlaceableAsset] | None = None,
) -> tuple[dict[str, list[Pose]], list[PlacementOutcome], int, dict[tuple[int, int], str]]:
    """Sample reset batches until ``min_layouts`` accepts or the batch budget is reached.

    Args:
        env: Built environment with a pooled placement reset event.
        min_layouts: Minimum accepted layouts to collect.
        max_batches: Maximum outer reset-and-settle rounds.
        params: Physics duration and post-physics validators.
        render: Render offline physics steps.
        scene_assets: Asset definitions for scene roots outside the placement pool.

    Returns:
        Accepted poses, validation outcomes, attempt count and rejection reasons.
    """
    from isaaclab_arena.offline_placement.settled_placement import collect_settled_placements

    assert min_layouts > 0 and max_batches > 0, "min_layouts and batch budget must be positive"
    poses: dict[str, list[Pose]] = {}
    outcomes: list[PlacementOutcome] = []
    rejections: dict[tuple[int, int], str] = {}
    attempted = 0
    for batch_index in range(max_batches):
        result = collect_settled_placements(env, 1, params, render=render, scene_assets=scene_assets, log_progress=True)
        attempted += result.attempted
        for (env_id, _), reason in result.rejections.items():
            rejections[env_id, batch_index] = reason
        remaining = min_layouts - len(outcomes)
        for key, values in result.poses.items():
            poses.setdefault(key, []).extend(values[:remaining])
        outcomes.extend(result.validation[:remaining])
        print(
            f"[recording] batch {batch_index + 1}/{max_batches}: {len(outcomes)}/{min_layouts} collected",
            flush=True,
        )
        if len(outcomes) >= min_layouts:
            break
    return poses, outcomes, attempted, rejections


def validate_recording_assets(env: ManagerBasedEnv, assets: list[PlaceableAsset]) -> None:
    """Require scene root ownership and reset policies compatible with reusable recordings.

    Args:
        env: Built environment whose writable physics roots will be recorded.
        assets: Placement and unplaced scene assets represented in the recording.
    """
    from isaaclab_arena.relations.geometry.bounding_box_helpers import has_heterogeneous_objects
    from isaaclab_arena.relations.placement_asset import get_scene_root_owners
    from isaaclab_arena.relations.runtime.placement_sampler import validate_root_reset_for_placement_replay

    env = env.unwrapped
    assert not has_heterogeneous_objects(assets), "Resolve object sets before recording reusable layouts"
    keys = set(env.scene.rigid_objects) | set(env.scene.articulations)
    owners = get_scene_root_owners(assets)
    assert keys <= owners.keys(), f"Pass scene_assets for unplaced scene roots: {keys - owners.keys()}"
    recorded_assets = []
    for asset in assets:
        owned_keys = set(asset.get_scene_root_keys())
        selected = owned_keys.intersection(keys)
        if selected or (not asset.is_anchor and asset.get_spatial_relations()):
            assert (
                owned_keys and owned_keys <= keys
            ), f"'{asset.name}' needs writable physics roots: {owned_keys - keys}"
        if selected:
            recorded_assets.append(asset)
    assert keys, "Recording requires rigid objects or articulations"
    validate_root_reset_for_placement_replay(recorded_assets)


def write_settled_layouts(
    env: ManagerBasedEnv,
    output: str | Path,
    assets: list[PlaceableAsset],
    poses: dict[str, list[Pose]],
    outcomes: list[PlacementOutcome],
    num_steps: int,
) -> None:
    """Write accepted root poses and their validation reports as episode JSONL.

    The caller validates recording compatibility before sampling and owns env.
    This function does not reset, step or close it. Existing output is never overwritten.
    """
    from isaaclab_arena.relations.runtime.placement_sampler import (
        placement_samples_from_pose_columns,
        validate_placement_sample_assets,
        write_placement_samples,
    )

    samples = placement_samples_from_pose_columns(poses)
    validate_placement_sample_assets(samples, assets)
    embodiment_keys = []
    for asset in assets:
        if asset.tags and "embodiment" in asset.tags:
            embodiment_keys.extend(asset.get_scene_root_keys())
    sampling = {
        "num_steps": num_steps,
        "decimation": env.unwrapped.cfg.decimation,
        "physics_dt_s": env.unwrapped.sim.get_physics_dt(),
        "embodiment_keys": embodiment_keys,
    }
    validation = []
    for outcome in outcomes:
        validation.append({
            "pre_physics": outcome.pre_physics,
            "post_physics": [asdict(report) for report in outcome.post_physics],
            "sampling": sampling,
        })
    write_placement_samples(output, samples, validation=validation)


def record_placements_to_jsonl(
    env: gym.Env,
    output: str | Path,
    *,
    min_layouts: int,
    max_batches: int,
    params: SettledPlacementParams | None = None,
    render: bool = False,
    scene_assets: list[PlaceableAsset] | None = None,
) -> PlacementRecordingSummary:
    """Collect accepted poses up to a target or batch budget and write them as JSONL."""
    from isaaclab_arena.offline_placement.settled_placement import resolve_settle_params
    from isaaclab_arena.relations.placement_events import get_placement_pool

    output = Path(output)
    assert not output.exists(), f"Output already exists: {output}"
    pool = get_placement_pool(env)
    assert pool is not None, "Recording requires a pooled placement reset event"
    assets = list(pool.objects)
    for asset in scene_assets or []:
        if asset not in assets:
            assets.append(asset)
    validate_recording_assets(env, assets)
    settle = resolve_settle_params(assets, params)
    poses, validation, attempted, rejections = collect_layouts_until_count(
        env,
        min_layouts,
        max_batches,
        settle,
        render=render,
        scene_assets=assets,
    )
    accepted = len(validation)
    summary = PlacementRecordingSummary(output=None, accepted=accepted, attempted=attempted, rejections=rejections)
    if accepted == 0:
        return summary
    write_settled_layouts(env, output, assets, poses, validation, settle.num_steps)
    summary.output = output
    return summary


def record_settled_placement_layouts(
    cfg: PlacementRecordingCfg,
    *,
    device: str = "cuda:0",
    arena_env: IsaacLabArenaEnvironment | None = None,
) -> PlacementRecordingSummary:
    """Build an environment, collect accepted settled poses, and close it."""
    from isaaclab_arena.assets.object_set import RigidObjectSet
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.environment_spec.placer_params_cfg_override import build_placer_params_from_override
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg

    assert not Path(cfg.output).exists(), f"Output already exists: {cfg.output}"
    assert cfg.num_envs > 0 and cfg.layouts_per_env > 0, "Environment and layout counts must be positive"
    assert cfg.min_layouts > 0 and cfg.max_batches > 0, "Layout target and batch budget must be positive"
    assert (
        cfg.max_batches * cfg.num_envs >= cfg.min_layouts
    ), "Batch budget cannot supply the requested accepted layout count"
    assert (cfg.viewer_eye is None) == (cfg.viewer_lookat is None), "Set viewer_eye and viewer_lookat together"

    if arena_env is None:
        spec = ArenaEnvGraphSpec.from_yaml(cfg.env_spec)
        assert not spec.object_sets, "Resolve object sets before recording reusable layouts"
        arena_env = spec.to_arena_env()
    scene_assets = arena_env.get_placement_assets()
    assert not any(isinstance(asset, RigidObjectSet) for asset in scene_assets), "Resolve object sets before recording"
    placer_params = arena_env.placer_params
    if placer_params is None:
        placer_params = build_placer_params_from_override(None)
    arena_env.placer_params = dataclass_replace(
        placer_params,
        placement_seed=cfg.seed,
        min_unique_layouts_per_env=cfg.layouts_per_env,
        resolve_on_reset=True,
    )

    print(f"[recording] Solving placements for {cfg.num_envs} environments...", flush=True)
    env = ArenaEnvBuilder(
        arena_env,
        ArenaEnvBuilderCfg(
            num_envs=cfg.num_envs,
            env_spacing=cfg.env_spacing,
            seed=cfg.seed,
            device=device,
            presets=cfg.presets,
        ),
    ).make_registered()
    try:
        if cfg.viewer_eye is not None:
            env.unwrapped.sim.set_camera_view(cfg.viewer_eye, cfg.viewer_lookat)
        return record_placements_to_jsonl(
            env,
            cfg.output,
            min_layouts=cfg.min_layouts,
            max_batches=cfg.max_batches,
            params=cfg.settle,
            render=cfg.render,
            scene_assets=scene_assets,
        )
    finally:
        env.close()
