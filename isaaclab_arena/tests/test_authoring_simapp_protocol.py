# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import io
import json

import pytest
from pydantic import ValidationError

from isaaclab_arena.agentic_environment_generation.simapp.protocol import (
    PROTOCOL_VERSION,
    RenderSpecRequest,
    parse_request,
    response_dict,
)
from isaaclab_arena.agentic_environment_generation.simapp.server import _serve_connection


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


def test_response_preserves_envelope_and_legacy_result_fields() -> None:
    request = parse_request({"cmd": "ping", "request_id": "request-1"})
    response = response_dict(request, result={"state": "ready"})
    assert response["protocol_version"] == PROTOCOL_VERSION
    assert response["request_id"] == "request-1"
    assert response["result"] == {"state": "ready"}
    assert response["state"] == "ready"


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
    assert not _serve_connection(reader, writer, app=None, render_fn=None, spec_cls=None, jobs=jobs)

    submit_response = json.loads(writer.getvalue())
    job_id = submit_response["job_id"]
    follow_up = [
        {"cmd": "status", "request_id": "status", "job_id": job_id},
        {"cmd": "cancel", "request_id": "cancel", "job_id": job_id},
        {"cmd": "result", "request_id": "result", "job_id": job_id},
    ]
    reader = io.StringIO("".join(json.dumps(request) + "\n" for request in follow_up))
    writer = io.StringIO()
    assert not _serve_connection(reader, writer, app=None, render_fn=None, spec_cls=None, jobs=jobs)
    status, cancel, result = (json.loads(line) for line in writer.getvalue().splitlines())
    assert status["state"] == "pending"
    assert cancel["state"] == "cancelled"
    assert result["error_code"] == "JOB_CANCELLED"
