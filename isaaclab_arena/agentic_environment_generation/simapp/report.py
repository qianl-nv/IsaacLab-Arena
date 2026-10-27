# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Machine-readable reports and artifact manifests for authoring commands."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

REPORT_SCHEMA_VERSION = "arena.authoring.v1"


class ReportModel(BaseModel):
    """Strict base class for authoring report models."""

    model_config = ConfigDict(extra="forbid")


class ArtifactRecord(ReportModel):
    """One file produced by an authoring command."""

    path: str
    media_type: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CheckRecord(ReportModel):
    """One structured validation check."""

    name: str
    status: Literal["passed", "failed", "incomplete", "unsupported"]
    message: str | None = None
    measurements: dict[str, Any] = Field(default_factory=dict)


class AuthoringReport(ReportModel):
    """Result envelope shared by all agentic authoring commands."""

    schema_version: Literal["arena.authoring.v1"] = REPORT_SCHEMA_VERSION
    command: str
    status: Literal["completed", "failed", "incomplete", "unsupported"]
    inputs: dict[str, Any] = Field(default_factory=dict)
    effective_configuration: dict[str, Any] = Field(default_factory=dict)
    checks: list[CheckRecord] = Field(default_factory=list)
    timings_s: dict[str, float] = Field(default_factory=dict)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    error_code: str | None = None
    error: str | None = None


def validated_output_dir(output: str | Path) -> Path:
    """Create and return a non-symlinked output directory."""
    output = Path(os.path.abspath(Path(output).expanduser()))
    for component in reversed((output, *output.parents)):
        if component.exists():
            assert not component.is_symlink(), f"Output path traverses a symlink: {component}"
    output.mkdir(parents=True, exist_ok=True)
    assert output.is_dir(), f"Output must be a directory: {output}"
    for component in reversed((output, *output.parents)):
        assert not component.is_symlink(), f"Output path traverses a symlink: {component}"
    return output.resolve()


def artifact_record(path: str | Path, output_dir: str | Path) -> ArtifactRecord:
    """Hash one artifact and express its path relative to the command output."""
    path = Path(path).resolve()
    output_dir = Path(output_dir).resolve()
    relative_path = path.relative_to(output_dir)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return ArtifactRecord(
        path=relative_path.as_posix(),
        media_type=media_type,
        size_bytes=path.stat().st_size,
        sha256=digest,
    )


def write_report(report: AuthoringReport, output_dir: str | Path) -> Path:
    """Write the report and return its path."""
    output_dir = validated_output_dir(output_dir)
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return report_path
