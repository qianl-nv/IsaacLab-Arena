# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Validate the Gym-native Open Microwave materialization path."""

from isaaclab_arena.tests.utils.persistent_simulation_app import run_function_with_persistent_simulation_app


def _test_gr1_open_microwave_materializer(simulation_app):
    import gymnasium as gym

    from isaaclab_tasks.utils import parse_env_cfg

    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
    from isaaclab_arena_environments.gr1_open_microwave_environment import (
        Gr1OpenMicrowaveEnvCfg,
        Gr1OpenMicrowaveEnvironment,
        Gr1OpenMicrowaveEnvironmentCfg,
        make_gr1_open_microwave_env_cfg,
    )

    task_name = "gr1_open_microwave"
    source_cfg = make_gr1_open_microwave_env_cfg()
    source_dict = source_cfg.to_dict()
    assert "arena_source" in source_dict
    assert "arena_materialization" in source_dict
    assert "__arena_environment__" not in source_dict

    spec = gym.spec(task_name)
    assert spec.entry_point.endswith(":IsaacLabArenaManagerBasedRLEnv")
    assert spec.kwargs["env_cfg_entry_point"] is make_gr1_open_microwave_env_cfg
    assert spec.kwargs["env_cfg_materializer_entry_point"].endswith(":materialize_gr1_open_microwave_env_cfg")

    materialized_cfg = parse_env_cfg(
        task_name,
        device="cpu",
        num_envs=2,
        use_fabric=False,
        overrides=[
            "env.arena_source.embodiment=gr1_joint",
            "env.arena_source.object=cracker_box",
            "env.arena_materialization.solve_relations=false",
        ],
    )
    assert isinstance(materialized_cfg, Gr1OpenMicrowaveEnvCfg) is False
    assert materialized_cfg._isaaclab_materialized is True
    assert materialized_cfg.scene.num_envs == 2
    assert materialized_cfg.sim.device == "cpu"
    assert materialized_cfg.sim.use_fabric is False
    assert materialized_cfg.decimation == 4
    assert materialized_cfg.sim.dt == 1 / 200
    assert "cracker_box" in vars(materialized_cfg.scene)

    legacy_cfg = Gr1OpenMicrowaveEnvironmentCfg(
        object="cracker_box",
        embodiment="gr1_joint",
    )
    legacy_env = Gr1OpenMicrowaveEnvironment().build(legacy_cfg)
    legacy_builder = ArenaEnvBuilder(
        legacy_env,
        ArenaEnvBuilderCfg(
            num_envs=2,
            solve_relations=False,
            device="cpu",
            disable_fabric=True,
        ),
    )
    legacy_manager_cfg, _ = legacy_builder._compose_manager_cfg_legacy()
    assert set(vars(materialized_cfg.scene)) == set(vars(legacy_manager_cfg.scene))
    assert set(vars(materialized_cfg.terminations)) == set(vars(legacy_manager_cfg.terminations))
    assert materialized_cfg.episode_length_s == legacy_manager_cfg.episode_length_s

    env = gym.make(task_name, cfg=materialized_cfg)
    try:
        env.reset()
        assert env.unwrapped.variation_recorder is not None
    finally:
        env.close()
    return True


def test_gr1_open_microwave_materializer():
    assert run_function_with_persistent_simulation_app(_test_gr1_open_microwave_materializer)
