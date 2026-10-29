#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Create gitless control and treatment snapshots for the Codex A/B pilot."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts" / "codex_collision_viz_ab"
TARGET = Path("isaaclab_arena_environments/kitchen_bench/kitchen_bench_lightwheel_open_microwave.yaml")
ARMS = {
    "arm_amber": "30d05dd06f986f7a6cff43e7631758b0e5353e57",
    "arm_cobalt": "4a63c78279cb55fcf13f3116d76c3da631d352bd",
}


def run(*args: str, cwd: Path = ROOT) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def export_repo(commit: str, destination: Path) -> None:
    destination.mkdir(parents=True)
    with tempfile.NamedTemporaryFile(suffix=".tar") as archive:
        run("git", "archive", "--format=tar", f"--output={archive.name}", commit)
        with tarfile.open(archive.name) as tar:
            tar.extractall(destination, filter="data")

    isaaclab_destination = destination / "submodules" / "IsaacLab"
    isaaclab_destination.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar") as archive:
        run(
            "git",
            "-C",
            str(ROOT / "submodules" / "IsaacLab"),
            "archive",
            "--format=tar",
            f"--output={archive.name}",
            "HEAD",
        )
        with tarfile.open(archive.name) as tar:
            tar.extractall(isaaclab_destination, filter="data")


def corrupt_yaml(snapshot: Path) -> None:
    target = snapshot / TARGET
    text = target.read_text()
    expected = """- kind: next_to
  subject: droid
  reference: microwave
  params:
    side: negative_y
    distance_m: 0.3
"""
    corrupted = expected.replace("side: negative_y", "side: positive_x")
    assert text.count(expected) == 1, f"Expected exactly one target relation in {target}"
    target.write_text(text.replace(expected, corrupted))


def file_manifest(snapshot: Path) -> dict[str, str]:
    manifest = {}
    for path in sorted(snapshot.rglob("*")):
        if path.is_file() and not path.is_symlink():
            manifest[str(path.relative_to(snapshot))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def main() -> None:
    snapshots = OUTPUT / "snapshots"
    if snapshots.exists():
        shutil.rmtree(snapshots)
    metadata = {}
    for arm, commit in ARMS.items():
        destination = snapshots / arm
        export_repo(commit, destination)
        corrupt_yaml(destination)
        metadata[arm] = {
            "commit": commit,
            "target": str(TARGET),
            "manifest": file_manifest(destination),
        }
    (snapshots / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
