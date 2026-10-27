# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from isaaclab_arena.agentic_environment_generation.simapp.report import (
    AuthoringReport,
    artifact_record,
    validated_output_dir,
    write_report,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "isaaclab_arena/scripts/arena_author.py"


def test_artifact_record_uses_relative_path_hash_and_media_type(tmp_path: Path) -> None:
    artifact = tmp_path / "images" / "frame.png"
    artifact.parent.mkdir()
    artifact.write_bytes(b"png")
    record = artifact_record(artifact, tmp_path)
    assert record.path == "images/frame.png"
    assert record.media_type == "image/png"
    assert record.size_bytes == 3
    assert record.sha256 == hashlib.sha256(b"png").hexdigest()


def test_output_dir_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(AssertionError, match="symlink"):
        validated_output_dir(link)


def test_write_report_emits_versioned_json(tmp_path: Path) -> None:
    report = AuthoringReport(command="graph preview", status="completed")
    report_path = write_report(report, tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "arena.authoring.v1"
    assert payload["status"] == "completed"


def test_status_command_prints_one_json_document_and_stable_failure_code(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--socket", str(tmp_path / "missing.sock"), "sim", "status"],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["command"] == "sim status"
    assert payload["status"] == "unavailable"


def test_failed_preview_still_writes_machine_readable_report(tmp_path: Path) -> None:
    output = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "graph",
            "preview",
            "--env-spec",
            str(tmp_path / "missing.yaml"),
            "--output",
            str(output),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 1
    stdout = json.loads(result.stdout)
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert stdout == report
    assert report["status"] == "failed"
    assert report["error_code"] == "FileNotFoundError"
