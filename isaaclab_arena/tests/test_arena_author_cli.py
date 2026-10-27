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


def test_expanded_env_yaml_inlines_external_graph_files() -> None:
    import yaml

    from isaaclab_arena.scripts.arena_author import _expanded_env_yaml

    path = _REPO_ROOT / "isaaclab_arena/tests/test_data/robolab_task_overlay.yaml"
    expanded = yaml.safe_load(_expanded_env_yaml(path))
    assert expanded["env_name"] == "banana_in_bowl"
    assert expanded["embodiment"]["registry_name"] == "droid_abs_joint_pos"
    assert expanded["background"]["registry_name"] == "maple_table_robolab"
    assert "external_yaml" not in expanded


def test_output_dir_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(AssertionError, match="symlink"):
        validated_output_dir(link)


def test_output_dir_rejects_existing_descendant_below_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    descendant = target / "existing"
    descendant.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(AssertionError, match="symlink"):
        validated_output_dir(link / "existing" / "new")


def test_artifact_record_rejects_path_escape(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        artifact_record(outside, output)


def test_write_report_emits_versioned_json(tmp_path: Path) -> None:
    report = AuthoringReport(command="graph preview", status="completed")
    report_path = write_report(report, tmp_path)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "arena.authoring.v1"
    assert payload["status"] == "completed"


def test_incomplete_report_retains_incremental_artifacts(tmp_path: Path) -> None:
    artifact = tmp_path / "partial.json"
    artifact.write_text('{"accepted": 1}\n', encoding="utf-8")
    report = AuthoringReport(
        command="scene check",
        status="incomplete",
        artifacts=[artifact_record(artifact, tmp_path)],
        error_code="PLACEMENT_TARGET_NOT_REACHED",
    )
    payload = json.loads(write_report(report, tmp_path).read_text(encoding="utf-8"))
    assert payload["status"] == "incomplete"
    assert payload["artifacts"][0]["path"] == "partial.json"
    assert payload["error_code"] == "PLACEMENT_TARGET_NOT_REACHED"


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


def test_force_session_requires_persistent_sidecar_with_json_only_stdout(tmp_path: Path) -> None:
    env_spec = tmp_path / "env.yaml"
    env_spec.write_text("env_name: unused\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--socket",
            str(tmp_path / "missing.sock"),
            "force",
            "serve",
            "--env-spec",
            str(env_spec),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["command"] == "force serve"
    assert payload["error_code"] == "SimAppError"


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
