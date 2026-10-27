# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Simulation lifecycle for finite and session-based physical-force commands."""

from __future__ import annotations

import contextlib
import traceback
import uuid
import yaml
from collections import defaultdict
from typing import Any

from isaaclab_arena.agentic_environment_generation.force.commands import (
    ForceCommand,
    JointEffortToCommand,
    parse_force_command,
    parse_force_commands,
)
from isaaclab_arena.agentic_environment_generation.force.controller import ForceController
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg


def _graph_spec(yaml_text: str) -> ArenaEnvGraphSpec:
    raw = yaml.safe_load(yaml_text)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected an environment-spec mapping, got {type(raw).__name__}.")
    return ArenaEnvGraphSpec.model_validate(raw)


def _containment_strategies(value: Any) -> list[str]:
    """Return explicitly configured containment geometry names."""
    strategies = []
    if isinstance(value, dict):
        for key, nested_value in value.items():
            if key == "containment_geometry" and isinstance(nested_value, str):
                strategies.append(nested_value)
            else:
                strategies.extend(_containment_strategies(nested_value))
    elif isinstance(value, list):
        for nested_value in value:
            strategies.extend(_containment_strategies(nested_value))
    return strategies


class ForceSession:
    """Own one environment and its physical-force controller."""

    def __init__(self, app, yaml_text: str, commands: list[ForceCommand] | None = None) -> None:
        import gymnasium as gym

        from isaaclab.actuators import ImplicitActuatorCfg

        from isaaclab_arena.agentic_environment_generation.simapp.environment_runtime import env_builder_from_graph_spec
        from isaaclab_arena.agentic_environment_generation.simapp.sim_preview import _close_env_and_reset_sim

        self.app = app
        self.env = None
        self.env_name = f"arena_force_{uuid.uuid4().hex[:12]}"
        self.closed = False
        self.command_count = 0
        self._gym = gym
        _close_env_and_reset_sim(suppress_exceptions=True, app=app)
        spec = _graph_spec(yaml_text)
        self.containment_strategies = sorted(set(_containment_strategies(spec.model_dump(mode="json")))) or [
            "world_aabb"
        ]
        builder_cfg = ArenaEnvBuilderCfg(
            num_envs=1,
            env_spacing=3.0,
            resolve_on_reset=False,
            disable_fabric=False,
            device="cpu",
        )
        builder = env_builder_from_graph_spec(spec, builder_cfg, env_name=self.env_name)
        env_cfg, env_kwargs = builder.build_env_cfg()

        effort_joints: dict[str, list[str]] = defaultdict(list)
        for command in commands or []:
            if isinstance(command, JointEffortToCommand):
                effort_joints[command.object_name].append(command.joint_name)
        for object_name, joint_names in effort_joints.items():
            asset_cfg = getattr(env_cfg.scene, object_name)
            asset_cfg.actuators = {
                "arena_author_force": ImplicitActuatorCfg(
                    joint_names_expr=sorted(set(joint_names)),
                    stiffness=0.0,
                    damping=0.0,
                    effort_limit_sim=10_000.0,
                ),
            }

        try:
            self.env = builder.make_registered(env_cfg, env_kwargs)
            observation, _ = self.env.reset()
            self.controller = ForceController(self.env, observation)
        except Exception:
            self.close()
            raise

    def execute(self, command_value: dict[str, Any] | ForceCommand) -> dict[str, Any]:
        """Validate and execute one command with failure diagnostics."""
        command = parse_force_command(command_value) if isinstance(command_value, dict) else command_value
        self.command_count += 1
        if self.command_count > 1000:
            return {
                "command_id": command.command_id,
                "action": command.action,
                "status": "failed",
                "error_code": "COMMAND_LIMIT_EXCEEDED",
                "error": "A force session supports at most 1000 commands.",
                "diagnostics": self.controller.inspect([]),
            }
        try:
            return self.controller.execute(command)
        except Exception as exc:
            with contextlib.suppress(Exception):
                diagnostics = self.controller.inspect([])
            if "diagnostics" not in locals():
                diagnostics = None
            return {
                "command_id": command.command_id,
                "action": command.action,
                "status": "failed",
                "error_code": type(exc).__name__,
                "error": str(exc),
                "diagnostics": diagnostics,
                "traceback": traceback.format_exc(),
            }

    def close(self) -> None:
        """Release commands, close the environment, and restore a clean stage."""
        if self.closed:
            return
        self.closed = True
        if hasattr(self, "controller"):
            with contextlib.suppress(Exception):
                self.controller.release_all()
        from isaaclab_arena.agentic_environment_generation.simapp.sim_preview import _close_env_and_reset_sim

        _close_env_and_reset_sim(self.env, suppress_exceptions=True, app=self.app)
        self.env = None
        if hasattr(self, "_gym") and self.env_name in self._gym.registry:
            del self._gym.registry[self.env_name]


def run_force_commands(app, yaml_text: str, command_values: list[dict[str, Any]]) -> dict[str, Any]:
    """Run a finite command list in one isolated environment."""
    commands = parse_force_commands(command_values)
    session = ForceSession(app, yaml_text, commands)
    acknowledgements = []
    try:
        for command in commands:
            acknowledgement = session.execute(command)
            acknowledgements.append(acknowledgement)
            if acknowledgement["status"] == "failed" or session.controller.finished:
                break
        final_state = session.controller.inspect()
        return {
            "status": (
                "completed"
                if len(acknowledgements) == len(commands)
                and all(item["status"] == "completed" for item in acknowledgements)
                else "incomplete"
            ),
            "commands_requested": len(commands),
            "commands_executed": len(acknowledgements),
            "acknowledgements": acknowledgements,
            "trace": list(session.controller.trace),
            "final_state": final_state,
            "lifecycle": {
                "setup": "environment construction and reset",
                "physical_commands": "normal env.step control lifecycle",
            },
            "containment_strategies": session.containment_strategies,
            "limitations": [
                "world_aabb measures intersecting AABB volume; transformed_vertices counts transformed "
                "cached vertices and is not a mesh-volume fraction."
            ],
        }
    finally:
        session.close()


def check_task_scenarios(app, yaml_text: str, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    """Run independently reset command scenarios and compare task outcomes."""
    assert 1 <= len(scenarios) <= 32, "Task checking supports between 1 and 32 scenarios."
    results = []
    for scenario in scenarios:
        allowed_keys = {"name", "commands", "expected_success", "expected_subtasks"}
        extra_keys = set(scenario) - allowed_keys
        assert not extra_keys, f"Unknown task scenario fields: {sorted(extra_keys)}"
        name = scenario.get("name")
        assert isinstance(name, str) and name, "Each task scenario requires a non-empty name."
        command_values = scenario.get("commands", [])
        assert isinstance(command_values, list), f"Scenario {name!r} commands must be a list."
        run_result = run_force_commands(app, yaml_text, command_values)
        progress = run_result["final_state"]["progress"]
        observed_success = bool(progress and progress["state"]["all_complete"])
        subtask_completion = _subtask_completion(run_result["final_state"])
        expected_success = scenario.get("expected_success")
        expected_subtasks = {
            int(index): bool(expected) for index, expected in scenario.get("expected_subtasks", {}).items()
        }
        expectation_errors = []
        if expected_success is not None and observed_success != bool(expected_success):
            expectation_errors.append(f"task success was {observed_success}, expected {bool(expected_success)}")
        for index, expected in expected_subtasks.items():
            if index >= len(subtask_completion):
                expectation_errors.append(f"subtask {index} does not exist")
            elif subtask_completion[index] != expected:
                expectation_errors.append(f"subtask {index} was {subtask_completion[index]}, expected {expected}")
        results.append({
            "name": name,
            "status": "completed" if not expectation_errors else "failed",
            "observed_success": observed_success,
            "subtask_completion": subtask_completion,
            "expectation_errors": expectation_errors,
            "run": run_result,
        })
    return {
        "status": "completed" if all(result["status"] == "completed" for result in results) else "incomplete",
        "scenarios": results,
        "isolation": "fresh environment per scenario",
        "containment_strategies": sorted(
            {strategy for result in results for strategy in result["run"]["containment_strategies"]}
        ),
    }


def _subtask_completion(state: dict[str, Any]) -> list[bool]:
    progress = state.get("progress")
    if progress is None:
        return []
    return [bool(value) for value in progress.get("subtask_completion", [])]
