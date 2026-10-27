# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from isaaclab_arena.agentic_environment_generation.force.commands import parse_force_command
from isaaclab_arena.agentic_environment_generation.simapp.protocol import (
    PROTOCOL_VERSION,
    RenderSpecRequest,
    parse_request,
    response_dict,
)
from isaaclab_arena.agentic_environment_generation.simapp.server import _serve_connection
from isaaclab_arena.agentic_environment_generation.simapp.sim_preview import _kit_camera_metadata


def test_protocol_request_defaults_version_and_request_id() -> None:
    request = parse_request({"cmd": "render_spec", "yaml_text": "env_name: test"})
    assert isinstance(request, RenderSpecRequest)
    assert request.protocol_version == PROTOCOL_VERSION
    assert request.request_id


def test_protocol_rejects_unknown_fields_and_invalid_bounds() -> None:
    with pytest.raises(ValidationError):
        parse_request({"cmd": "run_sim_preview", "yaml_text": "x", "num_envs": 0, "num_steps": 1, "env_spacing": 1})
    with pytest.raises(ValidationError):
        parse_request({"cmd": "ping", "unexpected": True})


@pytest.mark.parametrize(
    "payload",
    [
        {"cmd": "inspect_asset", "usd_path": "asset.usd"},
        {"cmd": "probe_asset", "yaml_text": "env_name: test", "object_name": "cube"},
        {
            "cmd": "check_scene",
            "yaml_text": "env_name: test",
            "output_path": "/tmp/report",
            "mode": "static",
        },
        {"cmd": "capture_evidence", "yaml_text": "env_name: test"},
        {
            "cmd": "run_force",
            "yaml_text": "env_name: test",
            "commands": [{"command_id": "inspect", "action": "inspect"}],
        },
        {
            "cmd": "check_task",
            "yaml_text": "env_name: test",
            "scenarios": [{"name": "initial", "commands": []}],
        },
    ],
)
def test_authoring_requests_are_typed(payload: dict) -> None:
    request = parse_request(payload)
    assert request.cmd == payload["cmd"]
    assert request.protocol_version == PROTOCOL_VERSION


def test_camera_metadata_uses_resolved_kit_visualizer_configuration() -> None:
    kit_cfg = SimpleNamespace(
        visualizer_type="kit",
        eye=(1.0, 2.0, 3.0),
        lookat=(0.0, 0.0, 0.5),
        focal_length=24.0,
        window_width=1280,
        window_height=720,
        origin_type="world",
        origin_env_index=0,
        origin_track_path=None,
    )
    metadata = _kit_camera_metadata(SimpleNamespace(sim=SimpleNamespace(visualizer_cfgs=[kit_cfg])))
    assert metadata["status"] == "completed"
    assert metadata["eye"] == [1.0, 2.0, 3.0]
    assert metadata["focal_length_mm"] == 24.0


def test_response_preserves_envelope_and_legacy_result_fields() -> None:
    request = parse_request({"cmd": "ping", "request_id": "request-1"})
    response = response_dict(request, result={"state": "ready"})
    assert response["protocol_version"] == PROTOCOL_VERSION
    assert response["request_id"] == "request-1"
    assert response["result"] == {"state": "ready"}
    assert response["state"] == "ready"


def test_force_commands_are_strict_and_bounded() -> None:
    command = parse_force_command({
        "command_id": "move-cube",
        "action": "move",
        "object_name": "cube",
        "goal": {"position_xyz": [0.1, 0.2, 0.3], "relative_to": "table"},
    })
    assert command.action == "move"
    assert command.goal.position_xyz == (0.1, 0.2, 0.3)
    with pytest.raises(ValidationError):
        parse_force_command({
            "command_id": "unbounded",
            "action": "wait",
            "duration_s": 31.0,
        })
    with pytest.raises(ValidationError):
        parse_force_command({
            "command_id": "typo",
            "action": "release",
            "object_name": "cube",
            "unexpected": True,
        })


def test_job_can_be_submitted_inspected_and_cancelled_without_execution() -> None:
    requests = [
        {
            "cmd": "submit",
            "request_id": "submit",
            "operation": {
                "cmd": "run_sim_preview",
                "yaml_text": "env_name: test",
                "num_envs": 1,
                "num_steps": 1,
                "env_spacing": 1.0,
            },
        },
    ]
    reader = io.StringIO("".join(json.dumps(request) + "\n" for request in requests))
    writer = io.StringIO()
    jobs = {}
    assert not _serve_connection(
        reader,
        writer,
        app=None,
        render_fn=None,
        spec_cls=None,
        jobs=jobs,
        force_sessions={},
    )

    submit_response = json.loads(writer.getvalue())
    job_id = submit_response["job_id"]
    follow_up = [
        {"cmd": "status", "request_id": "status", "job_id": job_id},
        {"cmd": "cancel", "request_id": "cancel", "job_id": job_id},
        {"cmd": "result", "request_id": "result", "job_id": job_id},
    ]
    reader = io.StringIO("".join(json.dumps(request) + "\n" for request in follow_up))
    writer = io.StringIO()
    assert not _serve_connection(
        reader,
        writer,
        app=None,
        render_fn=None,
        spec_cls=None,
        jobs=jobs,
        force_sessions={},
    )
    status, cancel, result = (json.loads(line) for line in writer.getvalue().splitlines())
    assert status["state"] == "pending"
    assert cancel["state"] == "cancelled"
    assert result["error_code"] == "JOB_CANCELLED"
