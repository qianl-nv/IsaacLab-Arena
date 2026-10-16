# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Compile Arena authoring components into complete Isaac Lab environment configs."""

from __future__ import annotations

import datetime
from typing import Any

from isaaclab.devices.device_base import DeviceCfg, DevicesCfg
from isaaclab.envs import ViewerCfg
from isaaclab.envs.mdp import time_out
from isaaclab.managers import EventTermCfg, TerminationTermCfg, event_add
from isaaclab.managers.recorder_manager import RecorderManagerBaseCfg
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.scene import add as scene_add
from isaaclab.visualizers import VisualizerCfg
from isaaclab_newton.physics import NewtonCfg
from isaaclab_physx.physics import PhysxCfg
from isaaclab_teleop import IsaacTeleopCfg

import isaaclab_arena_curobo  # noqa: F401
from isaaclab_arena.assets.registries import DeviceRegistry
from isaaclab_arena.embodiments.no_embodiment import NoEmbodiment
from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
from isaaclab_arena.environments.isaaclab_arena_environment import IsaacLabArenaEnvironment
from isaaclab_arena.environments.isaaclab_arena_manager_based_env_cfg import (
    ArenaPhysicsCfg,
    IsaacArenaManagerBasedMimicEnvCfg,
    IsaacLabArenaManagerBasedRLEnvCfg,
)
from isaaclab_arena.environments.relation_solver_interface import (
    make_placement_event,
    prepare_live_relation_placement,
    prepare_recorded_relation_placement,
)
from isaaclab_arena.metrics.metric_base import MetricBase
from isaaclab_arena.metrics.metric_term_cfg import MetricTermCfg
from isaaclab_arena.metrics.recorder_manager_utils import metrics_to_recorder_manager_cfg
from isaaclab_arena.progress_tracking.task_progress_cfg import TaskProgressCfg
from isaaclab_arena.recording.common_terms import (
    CoreEpisodeRecorderTermCfg,
    PlacementEpisodeRecorderTermCfg,
    VariationEpisodeRecorderTermCfg,
)
from isaaclab_arena.recording.episode_recorder_manager import EpisodeRecorderTermCfg
from isaaclab_arena.recording.progress_terms import ProgressEpisodeRecorderTermCfg
from isaaclab_arena.relations.object_placer_params import ObjectPlacerParams
from isaaclab_arena.relations.placement_events import PLACEMENT_RESET_EVENT_NAME
from isaaclab_arena.relations.placement_sampler import (
    PlacementSampler,
    RecordedPlacementSampler,
    serialize_placement_samples,
    supports_recorded_placement,
)
from isaaclab_arena.relations.relation_solver_params import RelationSolverParams
from isaaclab_arena.tasks.no_task import NoTask
from isaaclab_arena.tasks.task_termination_cfg import TaskTerminationCfg
from isaaclab_arena.tasks.terminations import task_success_from_progress
from isaaclab_arena.terms.events import ResetBackgroundPhysics
from isaaclab_arena.terms.recorders import ArenaEnvRecorderManagerCfg
from isaaclab_arena.utils.configclass import combine_configclass_instances, make_configclass
from isaaclab_arena.utils.multiprocess import get_local_rank
from isaaclab_arena.utils.physics_backend import PhysicsBackend
from isaaclab_arena.variations import variations_hydra
from isaaclab_arena.variations.recorded_variation_replay import configure_recorded_variation_replay
from isaaclab_arena.variations.variation_base import RunTimeVariationBase, VariationBase
from isaaclab_arena.variations.variation_recorder import VariationRecorder
from isaaclab_arena.variations.variation_replay_scheduler import VariationReplayScheduler


def configure_arena_visualizer_defaults(env_cfg: IsaacLabArenaManagerBasedRLEnvCfg) -> None:
    """Preserve Arena's scene background and migrate its legacy task camera configuration."""
    from isaaclab.envs.common import _apply_deprecated_viewer_cfg

    if env_cfg.sim.default_visualizer_cfg is None:
        _apply_deprecated_viewer_cfg(env_cfg)
    visualizer_cfg = env_cfg.sim.default_visualizer_cfg
    if visualizer_cfg is None:
        visualizer_cfg = VisualizerCfg(background_color=None)
    elif visualizer_cfg.background_color == VisualizerCfg().background_color:
        visualizer_cfg.background_color = None
    env_cfg.sim.default_visualizer_cfg = visualizer_cfg
    env_cfg.viewer = ViewerCfg()


def resolve_physics_backend(
    arena_env: IsaacLabArenaEnvironment,
    cfg: ArenaEnvBuilderCfg,
) -> PhysicsBackend:
    """Return the selected physics backend."""
    return cfg.presets if cfg.presets is not None else arena_env.default_physics_backend


def collect_asset_variations(arena_env: IsaacLabArenaEnvironment) -> dict[str, list[VariationBase]]:
    """Collect variations from every scene asset and the embodiment."""
    variations = arena_env.scene.get_asset_variations()
    if arena_env.embodiment is not None:
        variations[arena_env.embodiment.name] = arena_env.embodiment.get_variations()
    return variations


def prepare_relation_placement(
    arena_env: IsaacLabArenaEnvironment,
    cfg: ArenaEnvBuilderCfg,
    scheduler: VariationReplayScheduler | None,
) -> PlacementSampler | RecordedPlacementSampler | None:
    """Prepare live or recorded relation placement."""
    if scheduler is not None and scheduler.variation_record.has_placement_samples:
        return prepare_recorded_relation_placement(
            replay_assets=arena_env.get_placement_assets(),
            scheduler=scheduler,
            num_envs=cfg.num_envs,
        )
    if not cfg.solve_relations:
        return None
    if arena_env.task is not None:
        arena_env.task.apply_reachability_constraints()
    placement_assets = arena_env.scene.get_objects_with_relations()
    embodiment = arena_env.embodiment
    if embodiment is not None and embodiment.get_relations():
        placement_assets.append(embodiment)

    placer_params = arena_env.placer_params
    if placer_params is None:
        placer_params = ObjectPlacerParams(
            solver_params=RelationSolverParams(verbose=False, save_position_history=False),
        )
    if cfg.placement_seed is not None:
        placer_params.placement_seed = cfg.placement_seed
    if cfg.resolve_on_reset is not None:
        placer_params.resolve_on_reset = cfg.resolve_on_reset
    placer_params.reachability_config.embodiment = arena_env.embodiment
    return prepare_live_relation_placement(
        placement_assets,
        num_envs=cfg.num_envs,
        placer_params=placer_params,
        scene_assets=arena_env.scene.assets.values(),
    )


def compose_variations_event_cfg(variations: dict[str, list[VariationBase]]) -> Any | None:
    """Build an event config for enabled run-time variations."""
    fields: list[tuple[str, type, EventTermCfg]] = []
    added_event_names: set[str] = set()
    for variations_per_asset in variations.values():
        for variation in variations_per_asset:
            if not variation.enabled or not isinstance(variation, RunTimeVariationBase):
                continue
            event_name, event_cfg = variation.build_event_cfg()
            assert event_name not in added_event_names, (
                f"Duplicate variation event term name '{event_name}'. "
                "Each variation must produce a unique name; consider prefixing with the asset name."
            )
            added_event_names.add(event_name)
            fields.append((event_name, EventTermCfg, event_cfg))
    if not fields:
        return None
    VariationsEventCfg = make_configclass("VariationsEventCfg", fields)
    return VariationsEventCfg()


def apply_build_time_variations(variations: dict[str, list[VariationBase]]) -> None:
    """Apply enabled build-time variations before materializing scene configs."""
    for asset_variations in variations.values():
        for variation in asset_variations:
            if variation.enabled:
                variation.configure_at_build_time()


def stamp_recorder_dataset_filename(recorder_cfg: RecorderManagerBaseCfg) -> RecorderManagerBaseCfg:
    """Append a timestamp and process rank to the recorder dataset filename."""
    base = getattr(recorder_cfg, "dataset_filename", "dataset")
    recorder_cfg.dataset_filename = f"{base}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}_rank{get_local_rank()}"
    return recorder_cfg


def compose_metrics_cfg(metrics: list[MetricBase] | None) -> object | None:
    """Build the metric-manager configuration."""
    if not metrics:
        return None
    fields = [(metric.name, MetricTermCfg, metric.get_metric_term_cfg()) for metric in metrics]
    return make_configclass("MetricsCfg", fields)()


def build_termination_manager_cfg(task_termination_cfg: TaskTerminationCfg) -> object:
    """Translate task termination semantics into an Isaac Lab manager config."""
    termination_terms = dict(task_termination_cfg.failures)
    if task_termination_cfg.timeout_s is not None:
        termination_terms["time_out"] = TerminationTermCfg(func=time_out, time_out=True)
    if task_termination_cfg.success:
        termination_terms["success"] = TerminationTermCfg(func=task_success_from_progress)
    fields = [(name, TerminationTermCfg, term) for name, term in termination_terms.items()]
    return make_configclass("TerminationsCfg", fields)()


def compose_episode_recorders_cfg(
    extra_terms: dict[str, EpisodeRecorderTermCfg] | None = None,
) -> object:
    """Build the Arena per-episode recorder configuration."""
    fields = [
        ("core", EpisodeRecorderTermCfg, CoreEpisodeRecorderTermCfg()),
        ("placement", EpisodeRecorderTermCfg, PlacementEpisodeRecorderTermCfg()),
        ("variations", EpisodeRecorderTermCfg, VariationEpisodeRecorderTermCfg()),
        ("progress", EpisodeRecorderTermCfg, ProgressEpisodeRecorderTermCfg()),
    ]
    for name, term_cfg in (extra_terms or {}).items():
        assert name not in {
            "core",
            "placement",
            "variations",
            "progress",
        }, f"Episode recorder term name '{name}' collides with a built-in term."
        fields.append((name, EpisodeRecorderTermCfg, term_cfg))
    return make_configclass("EpisodeRecorderManagerCfg", fields)()


def compile_arena_manager_cfg(
    arena_env: IsaacLabArenaEnvironment,
    cfg: ArenaEnvBuilderCfg,
    hydra_overrides: list[str] | None = None,
) -> tuple[IsaacLabArenaManagerBasedRLEnvCfg, dict[str, Any]]:
    """Compile an Arena authoring graph into a complete Isaac Lab manager config."""
    variations = collect_asset_variations(arena_env)
    if hydra_overrides:
        variations_hydra.apply_overrides(variations, hydra_overrides)

    variation_replay_scheduler = None
    if cfg.recorded_variation_samples_path is not None:
        variation_replay_scheduler = configure_recorded_variation_replay(
            cfg.recorded_variation_samples_path,
            variations,
        )
    placement_sampler = prepare_relation_placement(arena_env, cfg, variation_replay_scheduler)

    variation_recorder = VariationRecorder()
    variation_recorder.attach(variations)
    if placement_sampler is not None and supports_recorded_placement(arena_env.get_placement_assets()):
        variation_recorder.attach_placement_sampler(placement_sampler, serialize_placement_samples)
    apply_build_time_variations(variations)

    resolved_physics_backend = resolve_physics_backend(arena_env, cfg)
    embodiment = arena_env.embodiment or NoEmbodiment()
    embodiment.configure_physics_backend(resolved_physics_backend)
    task = arena_env.task or NoTask()
    task.configure_for_embodiment(embodiment)

    scene_cfg = InteractiveSceneCfg(
        num_envs=cfg.num_envs,
        env_spacing=cfg.env_spacing,
        replicate_physics=False,
    )
    for source_scene in (
        arena_env.scene.get_scene_cfg(),
        embodiment.get_scene_cfg(),
        task.get_scene_cfg(),
    ):
        scene_add(scene_cfg, source_scene, mode="merge", on_conflict="replace")

    observation_cfg = combine_configclass_instances(
        "ObservationCfg",
        arena_env.scene.get_observation_cfg(),
        embodiment.get_observation_cfg(),
        task.get_observation_cfg(),
    )

    placement_event_cfg = None
    if placement_sampler is not None:
        PlacementEventCfg = make_configclass(
            "PlacementEventCfg",
            [(PLACEMENT_RESET_EVENT_NAME, EventTermCfg, make_placement_event(placement_sampler))],
        )
        placement_event_cfg = PlacementEventCfg()
    variations_event_cfg = compose_variations_event_cfg(variations)

    task_termination_cfg = task.get_termination_cfg()
    assert isinstance(
        task_termination_cfg, TaskTerminationCfg
    ), "Tasks must return TaskTerminationCfg with success criteria, failures, and timeout_s."

    background_physics_events_cfg = None
    background_physics_paths = arena_env.scene.get_background_physics_paths()
    if background_physics_paths:
        reset_background_physics = EventTermCfg(
            func=ResetBackgroundPhysics,
            mode="reset",
            params={
                "background_prim_paths": arena_env.scene.get_background_physics_prim_paths(),
                "physics_paths": background_physics_paths,
                "referenced_paths": arena_env.scene.get_background_physics_referenced_paths(),
            },
        )
        BackgroundPhysicsEventsCfg = make_configclass(
            "BackgroundPhysicsEventsCfg",
            [("reset_background_physics", EventTermCfg, reset_background_physics)],
        )
        background_physics_events_cfg = BackgroundPhysicsEventsCfg()

    event_terms: dict[str, EventTermCfg] = {}
    for source_events in (
        background_physics_events_cfg,
        embodiment.get_events_cfg(),
        arena_env.scene.get_events_cfg(),
        task.get_events_cfg(),
        placement_event_cfg,
        variations_event_cfg,
    ):
        event_add(event_terms, source_events)
    EventsCfg = make_configclass(
        "EventsCfg",
        [(name, EventTermCfg, term_cfg) for name, term_cfg in event_terms.items()],
    )
    events_cfg = EventsCfg()

    termination_cfg = build_termination_manager_cfg(task_termination_cfg)
    task_progress_cfg = None
    if task_termination_cfg.success:
        task_progress_cfg = TaskProgressCfg(
            success_criteria=task_termination_cfg.success,
            subtasks_are_sequential=task_termination_cfg.subtasks_are_sequential,
            desired_subtask_success_state=task_termination_cfg.desired_subtask_success_state,
        )

    actions_cfg = embodiment.get_action_cfg()
    xr_cfg = embodiment.get_xr_cfg()
    isaac_teleop_cfg = None
    teleop_devices_cfg = None
    if arena_env.teleop_device is not None:
        device_cfg = DeviceRegistry().get_teleop_device_cfg(arena_env.teleop_device, arena_env.embodiment)
        if isinstance(device_cfg, IsaacTeleopCfg):
            isaac_teleop_cfg = device_cfg
        elif isinstance(device_cfg, DeviceCfg):
            teleop_devices_cfg = DevicesCfg(devices={arena_env.teleop_device.name: device_cfg})

    metrics = task.get_metrics()
    metrics_cfg = compose_metrics_cfg(metrics)
    metrics_recorder_manager_cfg = metrics_to_recorder_manager_cfg(metrics)
    recorder_manager_cfg = combine_configclass_instances(
        "RecorderManagerCfg",
        metrics_recorder_manager_cfg,
        task.get_recorder_term_cfg(),
        embodiment.get_recorder_term_cfg(record_trajectories=cfg.record_trajectories),
        bases=(RecorderManagerBaseCfg,),
    )
    recorder_manager_cfg = stamp_recorder_dataset_filename(recorder_manager_cfg)
    if cfg.recorder_dataset_filename is not None:
        recorder_manager_cfg.dataset_filename = cfg.recorder_dataset_filename
    if cfg.recorder_dataset_export_dir_path is not None:
        recorder_manager_cfg.dataset_export_dir_path = cfg.recorder_dataset_export_dir_path

    rewards_cfg = combine_configclass_instances(
        "RewardsCfg",
        arena_env.scene.get_rewards_cfg(),
        embodiment.get_rewards_cfg(),
        task.get_rewards_cfg(),
    )
    curriculum_cfg = combine_configclass_instances(
        "CurriculumCfg",
        arena_env.scene.get_curriculum_cfg(),
        embodiment.get_curriculum_cfg(),
        task.get_curriculum_cfg(),
    )
    commands_cfg = combine_configclass_instances(
        "CommandsCfg",
        arena_env.scene.get_commands_cfg(),
        embodiment.get_commands_cfg(),
        task.get_commands_cfg(),
    )
    episode_recorders_cfg = compose_episode_recorders_cfg(arena_env.episode_recorder_terms)
    viewer_cfg = task.get_viewer_cfg()
    episode_length_s = task_termination_cfg.timeout_s
    if episode_length_s is None:
        episode_length_s = task.get_episode_length_s()
    task_description = cfg.language_instruction or task.get_task_description()
    demo_recorder_config = ArenaEnvRecorderManagerCfg() if embodiment.enable_cameras else None

    if not cfg.mimic:
        env_cfg = IsaacLabArenaManagerBasedRLEnvCfg(
            observations=observation_cfg,
            actions=actions_cfg,
            events=events_cfg,
            scene=scene_cfg,
            terminations=termination_cfg,
            task_progress=task_progress_cfg,
            rewards=rewards_cfg,
            curriculum=curriculum_cfg,
            commands=commands_cfg,
            xr=xr_cfg,
            isaac_teleop=isaac_teleop_cfg,
            teleop_devices=teleop_devices_cfg,
            recorders=recorder_manager_cfg,
            demo_recorder_config=demo_recorder_config,
            metrics=metrics_cfg,
            episode_recorders=episode_recorders_cfg,
            task_description=task_description,
            viewer=viewer_cfg,
        )
        env_cfg.episode_length_s = episode_length_s
    else:
        assert not isinstance(embodiment, NoEmbodiment), "Mimic mode requires an embodiment to be specified"
        assert not isinstance(task, NoTask), "Mimic mode requires a task to be specified"
        task_mimic_env_cfg = task.get_mimic_env_cfg(arm_mode=arena_env.embodiment.arm_mode)
        mimic_recorder_config = task_mimic_env_cfg.mimic_recorder_config or demo_recorder_config
        env_cfg = IsaacArenaManagerBasedMimicEnvCfg(
            observations=observation_cfg,
            actions=actions_cfg,
            events=events_cfg,
            scene=scene_cfg,
            terminations=termination_cfg,
            task_progress=task_progress_cfg,
            rewards=rewards_cfg,
            curriculum=curriculum_cfg,
            commands=commands_cfg,
            xr=xr_cfg,
            isaac_teleop=isaac_teleop_cfg,
            teleop_devices=teleop_devices_cfg,
            demo_recorder_config=demo_recorder_config,
            datagen_config=task_mimic_env_cfg.datagen_config,
            subtask_configs=task_mimic_env_cfg.subtask_configs,
            task_constraint_configs=task_mimic_env_cfg.task_constraint_configs,
            mimic_recorder_config=mimic_recorder_config,
            task_description=task_description,
            viewer=viewer_cfg,
        )

    env_cfg.seed = cfg.seed
    arena_physics = ArenaPhysicsCfg()
    if resolved_physics_backend is PhysicsBackend.PHYSX:
        env_cfg.sim.physics = arena_physics.physx
    elif resolved_physics_backend is PhysicsBackend.NEWTON:
        env_cfg.sim.physics = arena_physics.newton
        env_cfg.scene.replicate_physics = True

    if arena_env.env_cfg_callback is not None:
        env_cfg = arena_env.env_cfg_callback(env_cfg)
        if resolved_physics_backend is PhysicsBackend.PHYSX:
            assert isinstance(
                env_cfg.sim.physics, PhysxCfg
            ), "env_cfg_callback changed the physics backend away from PhysX."
        elif resolved_physics_backend is PhysicsBackend.NEWTON:
            assert isinstance(
                env_cfg.sim.physics, NewtonCfg
            ), "env_cfg_callback changed the physics backend away from Newton."

    return env_cfg, {
        "variation_recorder": variation_recorder,
        "variation_replay_scheduler": variation_replay_scheduler,
    }
