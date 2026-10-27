# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Versioned request and response models for the authoring SimApp sidecar."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL_VERSION = "arena.simapp.v1"
MAX_REQUEST_BYTES = 16 * 1024 * 1024


class ProtocolModel(BaseModel):
    """Strict base model shared by sidecar protocol messages."""

    model_config = ConfigDict(extra="forbid")


class RequestBase(ProtocolModel):
    """Fields present on every sidecar request."""

    protocol_version: Literal["arena.simapp.v1"] = PROTOCOL_VERSION
    request_id: str = Field(default_factory=lambda: uuid4().hex, min_length=1, max_length=128)


class PingRequest(RequestBase):
    cmd: Literal["ping"] = "ping"


class ShutdownRequest(RequestBase):
    cmd: Literal["shutdown"] = "shutdown"


class CapabilitiesRequest(RequestBase):
    cmd: Literal["capabilities"] = "capabilities"


class RenderSpecRequest(RequestBase):
    cmd: Literal["render_spec"] = "render_spec"
    yaml_text: str = Field(max_length=8 * 1024 * 1024)
    background_panorama: bool = False


class RunSimPreviewRequest(RequestBase):
    cmd: Literal["run_sim_preview"] = "run_sim_preview"
    yaml_text: str = Field(max_length=8 * 1024 * 1024)
    num_envs: int = Field(ge=1, le=128)
    num_steps: int = Field(ge=1, le=100_000)
    env_spacing: float = Field(gt=0.0, le=1000.0)


class InspectAssetRequest(RequestBase):
    cmd: Literal["inspect_asset"] = "inspect_asset"
    usd_path: str = Field(min_length=1, max_length=8192)
    variants: dict[str, str] = Field(default_factory=dict)


class ProbeAssetRequest(RequestBase):
    cmd: Literal["probe_asset"] = "probe_asset"
    yaml_text: str = Field(max_length=8 * 1024 * 1024)
    object_name: str = Field(min_length=1, max_length=256)
    num_steps: int = Field(default=30, ge=1, le=10_000)
    env_spacing: float = Field(default=3.0, gt=0.0, le=1000.0)


class SceneCheckRequest(RequestBase):
    cmd: Literal["check_scene"] = "check_scene"
    yaml_text: str = Field(max_length=8 * 1024 * 1024)
    output_path: str = Field(min_length=1, max_length=8192)
    mode: Literal["sampled", "pool", "static"] = "sampled"
    configuration: dict[str, Any] = Field(default_factory=dict)


class CaptureEvidenceRequest(RequestBase):
    cmd: Literal["capture_evidence"] = "capture_evidence"
    yaml_text: str = Field(max_length=8 * 1024 * 1024)
    num_envs: int = Field(default=1, ge=1, le=128)
    num_steps: int = Field(default=20, ge=1, le=100_000)
    env_spacing: float = Field(default=3.0, gt=0.0, le=1000.0)


JobOperation = Annotated[
    RenderSpecRequest | RunSimPreviewRequest | ProbeAssetRequest | SceneCheckRequest | CaptureEvidenceRequest,
    Field(discriminator="cmd"),
]


class SubmitJobRequest(RequestBase):
    cmd: Literal["submit"] = "submit"
    operation: JobOperation


class JobStatusRequest(RequestBase):
    cmd: Literal["status"] = "status"
    job_id: str = Field(min_length=1, max_length=128)


class JobResultRequest(RequestBase):
    cmd: Literal["result"] = "result"
    job_id: str = Field(min_length=1, max_length=128)


class CancelJobRequest(RequestBase):
    cmd: Literal["cancel"] = "cancel"
    job_id: str = Field(min_length=1, max_length=128)


Request = Annotated[
    PingRequest
    | ShutdownRequest
    | CapabilitiesRequest
    | RenderSpecRequest
    | RunSimPreviewRequest
    | InspectAssetRequest
    | ProbeAssetRequest
    | SceneCheckRequest
    | CaptureEvidenceRequest
    | SubmitJobRequest
    | JobStatusRequest
    | JobResultRequest
    | CancelJobRequest,
    Field(discriminator="cmd"),
]
_REQUEST_ADAPTER = TypeAdapter(Request)


class Response(ProtocolModel):
    """Response envelope returned for every valid request."""

    protocol_version: Literal["arena.simapp.v1"] = PROTOCOL_VERSION
    request_id: str
    ok: bool
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error: str | None = None


def parse_request(payload: dict[str, Any]) -> Request:
    """Validate and convert one decoded JSON request."""
    return _REQUEST_ADAPTER.validate_python(payload)


def response_dict(
    request: RequestBase,
    *,
    result: dict[str, Any] | None = None,
    error_code: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build a serialized response while retaining legacy top-level result fields."""
    ok = error_code is None
    response = Response(
        request_id=request.request_id,
        ok=ok,
        result=result,
        error_code=error_code,
        error=error,
    ).model_dump()
    if ok and result:
        response.update(result)
    return response
