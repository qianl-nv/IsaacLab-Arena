# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Relation-solver rollout preview for the review GUI SimApp server."""

from __future__ import annotations

import shutil
import sys
import time
import uuid
from contextlib import nullcontext, suppress
from typing import Any

from isaaclab_arena.agentic_environment_generation.simapp.kit_viewport import (
    CAPTURE_DONE_TAIL_UPDATES,
    pump_app,
    sim_preview_cache_dir,
)
from isaaclab_arena.agentic_environment_generation.spec_io import safe_filename_stem
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
from isaaclab_arena.utils.isaaclab_utils.simulation_app import (
    collect_garbage_and_clear_cuda_cache,
    teardown_simulation_app,
)

# Placement pool size when preview uses resolve_on_reset=False (see ObjectPlacerParams).
_PREVIEW_LAYOUTS_PER_ENV = 2


def parse_sim_preview_params(req: dict[str, Any]) -> tuple[int, int, float]:
    """Read required sim-preview rollout settings from a JSON-RPC request."""
    missing = [key for key in ("num_envs", "num_steps", "env_spacing") if key not in req]
    if missing:
        raise ValueError(f"missing required sim preview params: {', '.join(missing)}")
    num_envs = int(req["num_envs"])
    num_steps = int(req["num_steps"])
    env_spacing = float(req["env_spacing"])
    assert num_envs >= 1, f"num_envs must be >= 1, got {num_envs}"
    assert num_steps >= 1, f"num_steps must be >= 1, got {num_steps}"
    assert env_spacing > 0, f"env_spacing must be > 0, got {env_spacing}"
    return num_envs, num_steps, env_spacing


def _preview_log(started_at: float, message: str) -> None:
    elapsed = time.monotonic() - started_at
    print(f"[sim_preview] +{elapsed:.1f}s {message}", file=sys.stderr, flush=True)


def _preview_cfg(*, num_envs: int, env_spacing: float) -> ArenaEnvBuilderCfg:
    return ArenaEnvBuilderCfg(
        num_envs=num_envs,
        env_spacing=env_spacing,
        resolve_on_reset=False,
        disable_fabric=True,
        device="cpu",
    )


def _close_env_and_reset_sim(
    env=None,
    *,
    suppress_exceptions: bool = False,
    app=None,
) -> None:
    """Close env and reset sim for the next preview."""
    error_manager = suppress(Exception) if suppress_exceptions else nullcontext()

    with error_manager:
        if env is not None and not getattr(env.unwrapped, "_is_closed", True):
            env.close()

    teardown_simulation_app(suppress_exceptions=suppress_exceptions, make_new_stage=True)

    if app is not None:
        with error_manager:
            pump_app(app, count=CAPTURE_DONE_TAIL_UPDATES)

    collect_garbage_and_clear_cuda_cache()


def run_sim_preview(
    app,
    yaml_text: str,
    *,
    num_envs: int,
    num_steps: int,
    env_spacing: float,
) -> dict[str, Any]:
    """Run relation-solver preview and record the task-configured viewport."""
    import gymnasium as gym
    import yaml

    from isaaclab.envs import VideoRecorderCfg

    from isaaclab_arena.agentic_environment_generation.simapp.environment_runtime import (
        env_builder_from_graph_spec,
        run_zero_action_steps,
    )

    started_at = time.monotonic()
    _preview_log(started_at, "run_sim_preview started")

    _close_env_and_reset_sim(suppress_exceptions=True, app=app)
    _preview_log(started_at, "cleared stale sim state")

    raw = yaml.safe_load(yaml_text)
    if not isinstance(raw, dict):
        raise ValueError(f"expected mapping, got {type(raw).__name__}")

    graph_spec = ArenaEnvGraphSpec.model_validate(raw)
    preview_name = f"{safe_filename_stem(graph_spec.env_name)}_preview_{uuid.uuid4().hex[:8]}"
    _preview_log(started_at, f"validated spec → arena env ({preview_name})")

    builder_cfg = _preview_cfg(num_envs=num_envs, env_spacing=env_spacing)
    builder = env_builder_from_graph_spec(graph_spec, builder_cfg, env_name=preview_name)

    cache_dir = sim_preview_cache_dir()
    stamp = int(time.time() * 1000)
    video_dir = cache_dir / f"{preview_name}_{stamp}"
    pool_layouts = builder_cfg.num_envs * _PREVIEW_LAYOUTS_PER_ENV
    env = None
    completed = False
    try:
        _preview_log(
            started_at,
            f"solving spatial relations ({builder_cfg.num_envs} envs, {pool_layouts} layout pool)…",
        )
        t_relations = time.monotonic()
        env_cfg, env_kwargs = builder.build_env_cfg()
        env_cfg.video_recorders = [
            VideoRecorderCfg(
                source="visualizer:kit",
                output_dir=str(video_dir),
                output_filename_prefix="preview",
                video_length=num_steps,
            )
        ]
        camera_metadata = _kit_camera_metadata(env_cfg)
        _preview_log(started_at, f"relation solver finished ({time.monotonic() - t_relations:.1f}s)")

        _preview_log(started_at, "spawning sim scene (gym.make)…")
        t_spawn = time.monotonic()
        env = builder.make_registered(env_cfg, env_kwargs)
        _preview_log(started_at, f"sim scene ready ({time.monotonic() - t_spawn:.1f}s)")
        camera_metadata = _active_kit_camera_metadata(camera_metadata)

        run_zero_action_steps(
            env,
            num_steps,
            inference_mode=False,
            reset_policy=False,
            handle_episode_ends=False,
        )

        env.close()
        env = None
        video_paths = sorted(video_dir.rglob("*.mp4"))
        if len(video_paths) != 1:
            raise RuntimeError(f"expected one viewport video, found {len(video_paths)}")

        print(
            f"[sim_preview] recorded {num_envs} envs @ {env_spacing}m spacing, {num_steps} zero-action steps "
            f"(total {time.monotonic() - started_at:.1f}s)",
            file=sys.stderr,
            flush=True,
        )
        completed = True
        return {
            "ok": True,
            "video_path": str(video_paths[0]),
            "env_name": preview_name,
            "num_envs": num_envs,
            "env_spacing": env_spacing,
            "num_steps": num_steps,
            "camera_metadata": camera_metadata,
        }
    finally:
        _close_env_and_reset_sim(env, app=app, suppress_exceptions=True)
        if not completed:
            shutil.rmtree(video_dir, ignore_errors=True)
        with suppress(Exception):
            if preview_name in gym.registry:
                del gym.registry[preview_name]


def _kit_camera_metadata(env_cfg) -> dict[str, Any]:
    """Return the effective Kit visualizer camera configuration."""
    visualizer_cfgs = getattr(env_cfg.sim, "visualizer_cfgs", ()) or ()
    cfg = next((cfg for cfg in visualizer_cfgs if getattr(cfg, "visualizer_type", None) == "kit"), None)
    if cfg is None:
        return {"status": "unsupported", "reason": "environment has no Kit visualizer configuration"}
    return {
        "status": "completed",
        "eye": list(cfg.eye),
        "lookat": list(cfg.lookat),
        "focal_length_mm": float(cfg.focal_length),
        "width_px": int(cfg.window_width),
        "height_px": int(cfg.window_height),
        "origin_type": str(cfg.origin_type),
        "origin_env_index": int(cfg.origin_env_index),
        "origin_track_path": cfg.origin_track_path,
        "provenance": "resolved_env_configuration",
    }


def _active_kit_camera_metadata(fallback: dict[str, Any]) -> dict[str, Any]:
    """Read the active viewport camera pose, intrinsics, and resolution."""
    try:
        import omni.usd
        from omni.kit.viewport.utility import get_active_viewport
        from pxr import Usd, UsdGeom

        viewport = get_active_viewport()
        stage = omni.usd.get_context().get_stage()
        camera_path = str(viewport.camera_path)
        camera = UsdGeom.Camera(stage.GetPrimAtPath(camera_path))
        assert camera, f"active viewport camera is invalid: {camera_path}"
        transform = UsdGeom.XformCache(Usd.TimeCode.Default()).GetLocalToWorldTransform(camera.GetPrim())
        translation = transform.ExtractTranslation()
        quaternion = transform.ExtractRotationQuat()
        imaginary = quaternion.GetImaginary()
        width_px, height_px = viewport.resolution
        focal_length_mm = float(camera.GetFocalLengthAttr().Get())
        horizontal_aperture_mm = float(camera.GetHorizontalApertureAttr().Get())
        vertical_aperture_mm = float(camera.GetVerticalApertureAttr().Get())
        return {
            "status": "completed",
            "camera_prim_path": camera_path,
            "position_w": [float(value) for value in translation],
            "rotation_wxyz": [
                float(quaternion.GetReal()),
                float(imaginary[0]),
                float(imaginary[1]),
                float(imaginary[2]),
            ],
            "focal_length_mm": focal_length_mm,
            "horizontal_aperture_mm": horizontal_aperture_mm,
            "vertical_aperture_mm": vertical_aperture_mm,
            "width_px": int(width_px),
            "height_px": int(height_px),
            "fx_px": focal_length_mm / horizontal_aperture_mm * width_px,
            "fy_px": focal_length_mm / vertical_aperture_mm * height_px,
            "provenance": "active_kit_viewport",
        }
    except Exception as exc:
        return {
            **fallback,
            "status": "incomplete",
            "reason": f"active viewport camera metadata unavailable: {exc}",
        }
