# Copyright (c) 2025-2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import gymnasium as gym
from copy import deepcopy
from typing import Any

from isaaclab.devices.device_base import DeviceCfg, DevicesCfg
from isaaclab.envs import ManagerBasedRLMimicEnv
from isaaclab.envs.manager_based_env import ManagerBasedEnv
from isaaclab.managers import EventTermCfg, event_add
from isaaclab.managers.recorder_manager import RecorderManagerBaseCfg
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.scene import add as scene_add
from isaaclab_newton.physics import NewtonCfg
from isaaclab_physx.physics import PhysxCfg
from isaaclab_tasks.utils import parse_env_cfg
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
    apply_arena_global_settings,
)
from isaaclab_arena.environments.relation_solver_interface import make_placement_event
from isaaclab_arena.metrics.metric_base import MetricBase
from isaaclab_arena.metrics.recorder_manager_utils import metrics_to_recorder_manager_cfg
from isaaclab_arena.progress_tracking.task_progress_cfg import TaskProgressCfg
from isaaclab_arena.recording.episode_recorder_manager import EpisodeRecorderTermCfg
from isaaclab_arena.relations.placement_events import PLACEMENT_RESET_EVENT_NAME
from isaaclab_arena.relations.placement_sampler import (
    PlacementSampler,
    RecordedPlacementSampler,
    serialize_placement_samples,
    supports_recorded_placement,
)
from isaaclab_arena.tasks.no_task import NoTask
from isaaclab_arena.tasks.task_termination_cfg import TaskTerminationCfg
from isaaclab_arena.terms.events import ResetBackgroundPhysics
from isaaclab_arena.terms.recorders import ArenaEnvRecorderManagerCfg
from isaaclab_arena.utils.configclass import combine_configclass_instances, make_configclass
from isaaclab_arena.utils.isaaclab_utils.warp_patch import install_empty_cpu_warp_to_torch_patch
from isaaclab_arena.utils.physics_backend import PhysicsBackend
from isaaclab_arena.variations import variations_hydra, variations_printing
from isaaclab_arena.variations.recorded_variation_replay import configure_recorded_variation_replay
from isaaclab_arena.variations.variation_base import VariationBase
from isaaclab_arena.variations.variation_recorder import VariationRecorder
from isaaclab_arena.variations.variation_replay_scheduler import VariationReplayScheduler


# TODO: peterd, 2026-09-16: Remove this once Arena migrates off ViewCfg and into KitVisualizerCfg.
def _configure_arena_visualizer_defaults(env_cfg: IsaacLabArenaManagerBasedRLEnvCfg) -> None:
    """Preserve Arena's native scene background and migrate its legacy task camera configuration.

    Compatibility layer to enable Arena's legacy ViewerCfg to work with Lab's default_visualizer_cfg.
    This can be removed once Arena migrates off ViewCfg and into KitVisualizerCfg.
    """
    from isaaclab_arena.environments.arena_env_compiler import configure_arena_visualizer_defaults

    configure_arena_visualizer_defaults(env_cfg)


class ArenaEnvBuilder:
    """Compose IsaacLab Arena → IsaacLab configs"""

    def __init__(
        self,
        arena_env: IsaacLabArenaEnvironment,
        cfg: ArenaEnvBuilderCfg,
        hydra_overrides: list[str] | None = None,
    ):
        self.arena_env = arena_env
        self.cfg = cfg
        self.hydra_overrides = hydra_overrides
        self.interactive_scene_cfg = InteractiveSceneCfg(
            num_envs=cfg.num_envs, env_spacing=cfg.env_spacing, replicate_physics=False
        )

    @property
    def resolved_physics_backend(self) -> PhysicsBackend:
        """Return the physics backend selected for this build (CLI preset or environment default)."""
        from isaaclab_arena.environments.arena_env_compiler import resolve_physics_backend

        return resolve_physics_backend(self.arena_env, self.cfg)

    def _prepare_relation_placement(
        self,
        scheduler: VariationReplayScheduler | None,
    ) -> PlacementSampler | RecordedPlacementSampler | None:
        """Prepare live or recorded relation placement.

        Recorded placement validates and binds native samples without constructing
        a solver pool. Live placement collects constrained assets and solves a pool.

        Live reset behaviour depends on ``ObjectPlacerParams.resolve_on_reset``.
        When the environment does not provide placer parameters, the builder creates
        them from ``ArenaEnvBuilderCfg``.

        * **True** (default) — registers a reset event that draws a fresh layout
          from the pool for each resetting environment.
        * **False** — assigns one fixed layout per environment and reuses it.

        Args:
            scheduler: Shared recorded-variation scheduler, if replay is enabled.

        Returns:
            The prepared live or recorded placement sampler, or ``None`` when placement is disabled.
        """
        from isaaclab_arena.environments.arena_env_compiler import prepare_relation_placement

        return prepare_relation_placement(self.arena_env, self.cfg, scheduler)

    def get_all_variations(self) -> dict[str, list[VariationBase]]:
        """Return ``{asset_name: [variation, ...]}`` for every variation host in the env.

        Merges scene variations with the embodiment own variations.
        """
        from isaaclab_arena.environments.arena_env_compiler import collect_asset_variations

        return collect_asset_variations(self.arena_env)

    def get_variations_catalogue_as_string(self) -> str:
        """Return a human-readable catalog of Hydra-configurable variations for this env."""
        variations: dict[str, list[VariationBase]] = self.get_all_variations()
        return variations_printing.get_variations_catalogue_as_string(variations, hydra_overrides=self.hydra_overrides)

    def _compose_variations_event_cfg(self) -> Any | None:
        """Build a configclass with one :class:`EventTermCfg` per enabled run-time variation.

        Returns ``None`` when no run-time variation is enabled.
        """
        from isaaclab_arena.environments.arena_env_compiler import compose_variations_event_cfg

        return compose_variations_event_cfg(self.get_all_variations())

    def _apply_build_time_variations(self) -> None:
        """Configure every enabled variation at build time before ``scene_cfg`` is materialised.

        These mutate asset configs in place (e.g. a dome light's spawner
        texture), so this must run before ``scene_cfg`` is materialised.
        """
        from isaaclab_arena.environments.arena_env_compiler import apply_build_time_variations

        apply_build_time_variations(self.get_all_variations())

    def _modify_recorder_cfg_dataset_filename(self, recorder_cfg: RecorderManagerBaseCfg) -> RecorderManagerBaseCfg:
        """Modify the recorder dataset filename to include the timestamp and rank."""
        from isaaclab_arena.environments.arena_env_compiler import stamp_recorder_dataset_filename

        return stamp_recorder_dataset_filename(recorder_cfg)

    def _compose_metrics_cfg(self, metrics: list[MetricBase] | None) -> object | None:
        """Build a configclass container with one ``MetricTermCfg`` field per metric."""
        from isaaclab_arena.environments.arena_env_compiler import compose_metrics_cfg

        return compose_metrics_cfg(metrics)

    def _build_termination_manager_cfg(
        self,
        task_termination_cfg: TaskTerminationCfg,
    ) -> object:
        """Translate TaskTerminationCfg into an Isaac Lab termination configclass.

        Args:
            task_termination_cfg: Task-owned success criteria, failures, and timeout.

        Returns:
            A configclass containing the requested failure, timeout, and success terms.
        """
        from isaaclab_arena.environments.arena_env_compiler import build_termination_manager_cfg

        return build_termination_manager_cfg(task_termination_cfg)

    def _compose_episode_recorders_cfg(self, extra_terms: dict[str, EpisodeRecorderTermCfg] | None = None) -> object:
        """Build a configclass container with one EpisodeRecorderTermCfg field per episode recorder term.

        Note that this function automatically adds the core, variations, and progress terms. The
        progress term records nothing for tasks that define no completion criteria.
        """
        from isaaclab_arena.environments.arena_env_compiler import compose_episode_recorders_cfg

        return compose_episode_recorders_cfg(extra_terms)

    def compose_manager_cfg(self) -> tuple[IsaacLabArenaManagerBasedRLEnvCfg, dict[str, Any]]:
        """Return the base ManagerBased cfg and the env kwargs (no registration).

        env_kwargs carries arguments to be forwarded to gym.make for construction of the IsaacLabArenaManagerBasedRLEnv.

        Returns:
            An (env_cfg, env_kwargs) tuple.
        """
        from isaaclab_arena.environments.environment_materializer import (
            make_arena_environment_source_cfg,
            materialize_arena_environment_cfg,
        )

        source_cfg = make_arena_environment_source_cfg(self.arena_env, self.cfg, self.hydra_overrides)
        env_cfg = materialize_arena_environment_cfg(source_cfg)
        env_kwargs = {
            "variation_recorder": env_cfg._variation_recorder,
            "variation_replay_scheduler": env_cfg._variation_replay_scheduler,
        }
        return env_cfg, env_kwargs

    def _compose_manager_cfg(self) -> tuple[IsaacLabArenaManagerBasedRLEnvCfg, dict[str, Any]]:
        """Compile the Arena source without passing through task registration."""
        from isaaclab_arena.environments.arena_env_compiler import compile_arena_manager_cfg

        return compile_arena_manager_cfg(self.arena_env, self.cfg, self.hydra_overrides)

    def _compose_manager_cfg_legacy(self) -> tuple[IsaacLabArenaManagerBasedRLEnvCfg, dict[str, Any]]:
        """Retain the pre-extraction implementation temporarily for parity testing."""
        # Apply Hydra variation overrides. Needs to happen before build-time variations are applied.
        variations = self.get_all_variations()
        if self.hydra_overrides:
            variations_hydra.apply_overrides(variations, self.hydra_overrides)

        variation_replay_scheduler = None
        if self.cfg.recorded_variation_samples_path is not None:
            variation_replay_scheduler = configure_recorded_variation_replay(
                self.cfg.recorded_variation_samples_path,
                variations,
            )
        # Placement needs its source selected before scene config captures construction poses.
        placement_sampler = self._prepare_relation_placement(variation_replay_scheduler)

        # Attach the variation recorder before any sampling, so it observes both build-time samples
        # (drawn just below) and run-time samples (drawn during simulation).
        variation_recorder = VariationRecorder()
        variation_recorder.attach(variations)
        # A RigidObjectSet's selected member identity is absent from pose-only samples, so skip unreplayable records.
        if placement_sampler is not None and supports_recorded_placement(self.arena_env.get_placement_assets()):
            variation_recorder.attach_placement_sampler(
                placement_sampler,
                serialize_placement_samples,
            )

        # Apply build-time variations now, before scene_cfg is materialised.
        self._apply_build_time_variations()

        resolved_physics_backend = self.resolved_physics_backend

        # Constructing the environment by combining inputs from the scene, embodiment, and task.
        embodiment = self.arena_env.embodiment or NoEmbodiment()
        embodiment.configure_physics_backend(resolved_physics_backend)
        task = self.arena_env.task or NoTask()
        task.configure_for_embodiment(embodiment)
        scene_cfg = deepcopy(self.interactive_scene_cfg)
        for source_scene in (
            self.arena_env.scene.get_scene_cfg(),
            embodiment.get_scene_cfg(),
            task.get_scene_cfg(),
        ):
            scene_add(
                scene_cfg,
                source_scene,
                mode="merge",
                on_conflict="replace",
            )
        observation_cfg = combine_configclass_instances(
            "ObservationCfg",
            self.arena_env.scene.get_observation_cfg(),
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
        variations_event_cfg = self._compose_variations_event_cfg()
        task_termination_cfg = task.get_termination_cfg()
        assert isinstance(
            task_termination_cfg, TaskTerminationCfg
        ), "Tasks must return TaskTerminationCfg with success criteria, failures, and timeout_s."
        background_physics_events_cfg = None
        background_physics_paths = self.arena_env.scene.get_background_physics_paths()
        if background_physics_paths:
            reset_background_physics = EventTermCfg(
                func=ResetBackgroundPhysics,
                mode="reset",
                params={
                    "background_prim_paths": self.arena_env.scene.get_background_physics_prim_paths(),
                    "physics_paths": background_physics_paths,
                    "referenced_paths": self.arena_env.scene.get_background_physics_referenced_paths(),
                },
            )
            BackgroundPhysicsEventsCfg = make_configclass(
                "BackgroundPhysicsEventsCfg",
                [("reset_background_physics", EventTermCfg, reset_background_physics)],
            )
            background_physics_events_cfg = BackgroundPhysicsEventsCfg()
        # Keep the background term first so its one-time snapshot observes the
        # composed startup state before any reset event can mutate scene entities.
        event_terms: dict[str, EventTermCfg] = {}
        for source_events in (
            background_physics_events_cfg,
            embodiment.get_events_cfg(),
            self.arena_env.scene.get_events_cfg(),
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
        termination_cfg = self._build_termination_manager_cfg(task_termination_cfg)
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
        if self.arena_env.teleop_device is not None:
            device_registry = DeviceRegistry()
            device_cfg = device_registry.get_teleop_device_cfg(self.arena_env.teleop_device, self.arena_env.embodiment)
            if isinstance(device_cfg, IsaacTeleopCfg):
                isaac_teleop_cfg = device_cfg
            elif isinstance(device_cfg, DeviceCfg):
                teleop_devices_cfg = DevicesCfg(devices={self.arena_env.teleop_device.name: device_cfg})
        metrics = task.get_metrics()
        metrics_cfg = self._compose_metrics_cfg(metrics)
        metrics_recorder_manager_cfg = metrics_to_recorder_manager_cfg(metrics)
        # Base has to be specified explicitly to avoid type errors and not lose inheritance.
        recorder_manager_cfg = combine_configclass_instances(
            "RecorderManagerCfg",
            metrics_recorder_manager_cfg,
            task.get_recorder_term_cfg(),
            embodiment.get_recorder_term_cfg(record_trajectories=self.cfg.record_trajectories),
            bases=(RecorderManagerBaseCfg,),
        )
        recorder_manager_cfg = self._modify_recorder_cfg_dataset_filename(recorder_manager_cfg)
        # Eval runs overwrite the timestamped default so rebuilds do not clobber each other.
        if self.cfg.recorder_dataset_filename is not None:
            recorder_manager_cfg.dataset_filename = self.cfg.recorder_dataset_filename
        if self.cfg.recorder_dataset_export_dir_path is not None:
            recorder_manager_cfg.dataset_export_dir_path = self.cfg.recorder_dataset_export_dir_path

        rewards_cfg = combine_configclass_instances(
            "RewardsCfg",
            self.arena_env.scene.get_rewards_cfg(),
            embodiment.get_rewards_cfg(),
            task.get_rewards_cfg(),
        )

        curriculum_cfg = combine_configclass_instances(
            "CurriculumCfg",
            self.arena_env.scene.get_curriculum_cfg(),
            embodiment.get_curriculum_cfg(),
            task.get_curriculum_cfg(),
        )

        commands_cfg = combine_configclass_instances(
            "CommandsCfg",
            self.arena_env.scene.get_commands_cfg(),
            embodiment.get_commands_cfg(),
            task.get_commands_cfg(),
        )

        episode_recorders_cfg = self._compose_episode_recorders_cfg(self.arena_env.episode_recorder_terms)

        viewer_cfg = task.get_viewer_cfg()

        episode_length_s = task_termination_cfg.timeout_s
        if episode_length_s is None:
            # Isaac Lab still needs a numeric episode length without timeout termination.
            episode_length_s = task.get_episode_length_s()

        task_description = self.cfg.language_instruction or task.get_task_description()

        demo_recorder_config = ArenaEnvRecorderManagerCfg() if embodiment.enable_cameras else None

        # Build the environment configuration
        if not self.cfg.mimic:
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
            # Tasks always resolve to a concrete episode length.
            env_cfg.episode_length_s = episode_length_s
        else:
            assert not isinstance(embodiment, NoEmbodiment), "Mimic mode requires an embodiment to be specified"
            assert not isinstance(task, NoTask), "Mimic mode requires a task to be specified"
            task_mimic_env_cfg = task.get_mimic_env_cfg(arm_mode=self.arena_env.embodiment.arm_mode)
            mimic_recorder_config = task_mimic_env_cfg.mimic_recorder_config
            if mimic_recorder_config is None:
                mimic_recorder_config = demo_recorder_config
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
                # Mimic stuff
                datagen_config=task_mimic_env_cfg.datagen_config,
                subtask_configs=task_mimic_env_cfg.subtask_configs,
                task_constraint_configs=task_mimic_env_cfg.task_constraint_configs,
                mimic_recorder_config=mimic_recorder_config,
                # NOTE(alexmillane, 2025-09-25): Metric + recorders excluded from mimic env,
                # I assume that they're not needed for the mimic env.
                # recorders=recorder_manager_cfg,
                # metrics=metrics_cfg,
                task_description=task_description,
                viewer=viewer_cfg,
            )

        # Set seed for Isaac Lab env.
        env_cfg.seed = self.cfg.seed

        arena_physics = ArenaPhysicsCfg()
        if resolved_physics_backend is PhysicsBackend.PHYSX:
            env_cfg.sim.physics = arena_physics.physx
        elif resolved_physics_backend is PhysicsBackend.NEWTON:
            env_cfg.sim.physics = arena_physics.newton
            # replicate_physics=False is not supported for Newton, so force it to True here.
            # submodules/IsaacLab/source/isaaclab/isaaclab/scene/interactive_scene_cfg.py:120
            env_cfg.scene.replicate_physics = True

        if self.arena_env.env_cfg_callback is not None:
            env_cfg = self.arena_env.env_cfg_callback(env_cfg)
            if resolved_physics_backend is PhysicsBackend.PHYSX:
                assert isinstance(
                    env_cfg.sim.physics, PhysxCfg
                ), "env_cfg_callback changed the physics backend away from PhysX."
            elif resolved_physics_backend is PhysicsBackend.NEWTON:
                assert isinstance(
                    env_cfg.sim.physics, NewtonCfg
                ), "env_cfg_callback changed the physics backend away from Newton."

        env_kwargs: dict[str, Any] = {
            "variation_recorder": variation_recorder,
            "variation_replay_scheduler": variation_replay_scheduler,
        }
        return env_cfg, env_kwargs

    def get_entry_point(self) -> str | type[ManagerBasedRLMimicEnv]:
        """Return the entry point of the environment."""
        if self.cfg.mimic:
            embodiment = self.arena_env.embodiment
            assert embodiment is not None and not isinstance(
                embodiment, NoEmbodiment
            ), "Mimic mode requires an embodiment to be specified"
            return embodiment.get_mimic_env()
        else:
            return "isaaclab_arena.environments.isaaclab_arena_manager_based_env:IsaacLabArenaManagerBasedRLEnv"

    def register(
        self,
        env_cfg: None | IsaacLabArenaManagerBasedRLEnvCfg = None,
    ) -> str:
        """Register a fresh source factory without compiling or sampling the environment.

        Args:
            env_cfg: Optional prebuilt config to register instead of an Arena source.

        Returns:
            The Gym environment name.
        """
        install_empty_cpu_warp_to_torch_patch()
        apply_arena_global_settings()
        name = self.arena_env.name
        materializer_entry_point = None
        if env_cfg is None:
            from isaaclab_arena.environments.environment_materializer import make_arena_environment_source_cfg

            source_cfg = make_arena_environment_source_cfg(self.arena_env, self.cfg, self.hydra_overrides)

            def env_cfg_entry_point():
                return deepcopy(source_cfg)

            registered_env_cfg = env_cfg_entry_point
            materializer_entry_point = (
                "isaaclab_arena.environments.environment_materializer:materialize_arena_environment_cfg"
            )
        else:
            registered_env_cfg = env_cfg
        entry_point = self.get_entry_point()
        # Register the environment with the Gym registry.
        # Runtime variation objects live only on the transient materialized cfg.
        # Keeping them out of Gym's process-global registry avoids retaining
        # environments and their simulation buffers across repeated builds.
        kwargs = {
            "env_cfg_entry_point": registered_env_cfg,
        }
        if materializer_entry_point is not None:
            kwargs["env_cfg_materializer_entry_point"] = materializer_entry_point
        if self.arena_env.rl_framework_entry_point is not None:
            kwargs[self.arena_env.rl_framework_entry_point] = self.arena_env.rl_policy_cfg
        gym.register(
            id=name,
            entry_point=entry_point,
            kwargs=kwargs,
            disable_env_checker=True,
        )
        return name

    def build_registered(
        self,
        env_cfg: None | IsaacLabArenaManagerBasedRLEnvCfg = None,
        env_kwargs: dict[str, Any] | None = None,
    ) -> tuple[str, IsaacLabArenaManagerBasedRLEnvCfg, dict[str, Any]]:
        """Register and materialize a config without creating an environment.

        Args:
            env_cfg: Optional prebuilt environment config.
            env_kwargs: Optional runtime kwargs for a prebuilt config.

        Returns:
            A ``(name, cfg, env_kwargs)`` tuple.
        """
        name = self.register(env_cfg)
        if env_cfg is None or env_kwargs is None:
            env_kwargs = {}
        cfg = parse_env_cfg(
            name,
            device=self.cfg.device,
            num_envs=self.cfg.num_envs,
            use_fabric=not self.cfg.disable_fabric,
        )
        _configure_arena_visualizer_defaults(cfg)
        self.arena_env.scene.validate_simulation_cfg(cfg.sim)
        if cfg.demo_recorder_config is not None:
            gym.spec(name).kwargs["demo_recorder_cfg_entry_point"] = cfg.demo_recorder_config
        return name, cfg, env_kwargs

    def make_registered(
        self,
        env_cfg: None | IsaacLabArenaManagerBasedRLEnvCfg = None,
        env_kwargs: dict[str, Any] | None = None,
        render_mode: str | None = None,
    ) -> ManagerBasedEnv:
        """Build env cfg, register the env with gym, and make the env.

        The default operation is to call with no arguments, in which case the env_cfg is built from the
        Arena description passed to the builder at construction.

        Args:
            env_cfg: The optional environment cfg to use.
            env_kwargs: The optional environment kwargs to use.
            render_mode: The optional render mode to use.

        Returns:
            The environment.
        """
        env, _ = self.make_registered_and_return_cfg(env_cfg, env_kwargs, render_mode=render_mode)
        return env

    def make_registered_and_return_cfg(
        self,
        env_cfg: None | IsaacLabArenaManagerBasedRLEnvCfg = None,
        env_kwargs: dict[str, Any] | None = None,
        render_mode: str | None = None,
    ) -> tuple[ManagerBasedEnv, IsaacLabArenaManagerBasedRLEnvCfg]:
        """Build env cfg, register the env with gym, and make the env.

        The default operation is to call with no arguments, in which case the env_cfg is built from the
        Arena description passed to the builder at construction.

        Args:
            env_cfg: The optional environment cfg to use.
            env_kwargs: The optional environment kwargs to use.
            render_mode: The optional render mode to use.

        Returns:
            A tuple containing the environment and the environment configuration.
        """
        name, cfg, env_kwargs = self.build_registered(env_cfg, env_kwargs)
        env = gym.make(name, cfg=cfg, render_mode=render_mode, **env_kwargs)
        return env, cfg
