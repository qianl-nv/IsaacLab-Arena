#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Run the same independent five-episode acceptance check for both A/B arms."""

from __future__ import annotations

import json
import shutil
import subprocess

from run_arm import RUNS, SNAPSHOTS, TARGET, docker_start

ARMS = ("arm_amber", "arm_cobalt")

ACCEPTANCE_SCRIPT = r"""
set -euo pipefail
cd /workspaces/isaaclab_arena
export PYTHONDONTWRITEBYTECODE=1
export PYTHONUNBUFFERED=1
export ISAACLAB_ARENA_FORCE_EXIT_ON_COMPLETE=1
isaaclab.sh -p - <<'PY'
import json
from pathlib import Path

from isaaclab_arena.cli.isaaclab_arena_cli import get_isaaclab_arena_cli_parser
from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext

args = get_isaaclab_arena_cli_parser().parse_args(
    ["--viz", "none", "--enable_cameras", "--device", "cpu"]
)
args.kit_args = "--/log/file=/results/acceptance/kit.log"
with SimulationAppContext(args):
    from isaaclab_arena.evaluation.arena_experiment import ArenaExperimentCfg
    from isaaclab_arena.evaluation.arena_experiment_config_loader import (
        load_arena_experiment_from_config_file,
    )
    from isaaclab_arena.evaluation.run_execution import execute_experiment

    run_name = "kitchen_bench_lightwheel_open_microwave_pi0"
    experiment = load_arena_experiment_from_config_file(
        "isaaclab_arena_environments/kitchen_bench/experiment_configs/"
        "kitchen_bench_17_tasks_pi0_and_cosmos.yaml",
        device="cpu",
        overrides=[
            f"runs.{run_name}.environment_builder.num_envs=1",
            f"runs.{run_name}.rollout_limit.num_episodes=5",
        ],
    )
    experiment = ArenaExperimentCfg(runs={run_name: experiment.runs[run_name]})
    run = experiment.runs[run_name]
    assert run.policy.policy_variant == "pi05"
    assert run.policy.remote_host == "127.0.0.1"
    assert run.policy.remote_port == 8000
    assert run.rollout_limit.num_episodes == 5
    results = execute_experiment(
        experiment,
        output_dir=Path("/results/acceptance/output"),
        record_camera_video=False,
    )
    assert len(results) == 1
    result = results[0]
    metrics = result.metrics
    assert metrics is not None
    success_rate = float(metrics.metric_data_entries["success_rate"].metric_value)
    payload = {
        "episodes": metrics.num_episodes,
        "successes": int(round(success_rate * metrics.num_episodes)),
        "success_rate": success_rate,
    }
    Path("/results/acceptance/result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
PY
"""


def run_arm_acceptance(arm: str) -> None:
    result_dir = RUNS / arm
    acceptance_dir = result_dir / "acceptance"
    if acceptance_dir.exists():
        shutil.rmtree(acceptance_dir)
    acceptance_dir.mkdir()
    (result_dir / "codex_home").mkdir(exist_ok=True)

    workspace = SNAPSHOTS / arm
    shutil.copy2(result_dir / "final_environment.yaml", workspace / TARGET)
    container = docker_start(f"acceptance-{arm}", workspace, result_dir)
    try:
        with (acceptance_dir / "run.log").open("w") as log:
            completed = subprocess.run(
                [
                    "docker",
                    "exec",
                    "--user",
                    "root",
                    container,
                    "sudo",
                    "-n",
                    "--preserve-env",
                    "-u",
                    "qianl",
                    "bash",
                    "-lc",
                    ACCEPTANCE_SCRIPT,
                ],
                text=True,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        (acceptance_dir / "run_record.json").write_text(
            json.dumps({"return_code": completed.returncode}, indent=2) + "\n"
        )
        if completed.returncode:
            raise RuntimeError(f"{arm} acceptance failed; see {acceptance_dir / 'run.log'}")
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main() -> None:
    for arm in ARMS:
        run_arm_acceptance(arm)


if __name__ == "__main__":
    main()
