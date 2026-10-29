#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Run one blinded Codex arm inside an isolated Arena container."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent
OUTPUT = ROOT / "artifacts" / "codex_collision_viz_ab"
SNAPSHOTS = OUTPUT / "snapshots"
RUNS = OUTPUT / "runs"
IMAGE = "dc264620a8d4"
CODEX_BINARY = Path(
    "/home/qianl/.local/lib/node_modules/@openai/codex/node_modules/@openai/"
    "codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex"
)
CODEX_CODE_MODE_HOST = CODEX_BINARY.with_name("codex-code-mode-host")
CODEX_AUTH = Path("/home/qianl/.codex/auth.json")
TARGET = Path("isaaclab_arena_environments/kitchen_bench/kitchen_bench_lightwheel_open_microwave.yaml")
TIMEOUT_SECONDS = 90 * 60


def run(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, text=True, **kwargs)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def workspace_changes(arm: str, workspace: Path) -> dict:
    metadata = json.loads((SNAPSHOTS / "metadata.json").read_text())[arm]
    before: dict[str, str] = metadata["manifest"]
    after = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts:
            after[str(path.relative_to(workspace))] = sha256(path)
    changed = sorted(path for path in before.keys() & after.keys() if before[path] != after[path])
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    allowed = changed == [str(TARGET)] and not added and not removed
    return {"allowed": allowed, "changed": changed, "added": added, "removed": removed}


def wait_for_container_user(container: str) -> None:
    for _ in range(30):
        completed = subprocess.run(
            ["docker", "exec", "--user", "root", container, "id", "qianl"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError(f"Container user was not created in {container}")


def docker_start(arm: str, workspace: Path, result: Path) -> str:
    container = f"codex-collision-ab-{arm}-{os.getpid()}"
    uid = str(os.getuid())
    gid = str(os.getgid())
    command = [
        "docker",
        "run",
        "--detach",
        "--name",
        container,
        "--gpus",
        "all",
        "--network",
        "host",
        "--ipc",
        "host",
        "-e",
        "DOCKER_RUN_USER_NAME=qianl",
        "-e",
        f"DOCKER_RUN_USER_ID={uid}",
        "-e",
        "DOCKER_RUN_GROUP_NAME=domain-users",
        "-e",
        f"DOCKER_RUN_GROUP_ID={gid}",
        "-e",
        "HOME=/home/qianl",
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        "PRIVACY_CONSENT=Y",
        "-e",
        "DISPLAY=:1",
        "-e",
        "ISAACLAB_PATH=/workspaces/isaaclab_arena/submodules/IsaacLab",
        "-e",
        "VIRTUAL_ENV=/opt/isaaclab-venv",
        "-e",
        "UV_PROJECT_ENVIRONMENT=/opt/isaaclab-venv",
        "-e",
        "UV_PYTHON_PREFERENCE=only-system",
        "-e",
        "UV_NO_SYNC=1",
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "CODEX_HOME=/home/qianl/.codex-ab",
        "-e",
        "REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt",
        "-v",
        f"{workspace}:/workspaces/isaaclab_arena",
        "-v",
        f"{result}:/results",
        "-v",
        f"{HARNESS}:/experiment:ro",
        "-v",
        f"{CODEX_BINARY}:/usr/local/bin/codex:ro",
        "-v",
        f"{CODEX_CODE_MODE_HOST}:/usr/local/bin/codex-code-mode-host:ro",
        "-v",
        f"{result / 'codex_home'}:/home/qianl/.codex-ab",
        "-v",
        "/home/qianl/.cache/ov:/home/qianl/.cache/ov",
        "-v",
        "/home/qianl/.cache/warp:/home/qianl/.cache/warp",
        "-v",
        "/tmp/.X11-unix:/tmp/.X11-unix:rw",
        "-v",
        "/home/qianl/.Xauthority:/home/qianl/.Xauthority:ro",
        "-v",
        "/etc/ssl/certs:/etc/ssl/certs:ro",
        IMAGE,
        "sleep infinity",
    ]
    run(*command, stdout=subprocess.DEVNULL)
    wait_for_container_user(container)
    run(
        "docker",
        "exec",
        "--user",
        "root",
        container,
        "bash",
        "-lc",
        "mkdir -p /home/qianl/.cache/isaaclab_arena"
        f" && chown {uid}:{gid} /home/qianl/.cache /home/qianl/.cache/isaaclab_arena",
    )
    return container


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("arm", choices=("arm_amber", "arm_cobalt"))
    args = parser.parse_args()

    workspace = SNAPSHOTS / args.arm
    result = RUNS / args.arm
    if result.exists():
        shutil.rmtree(result)
    result.mkdir(parents=True)
    (result / "images").mkdir()
    (result / "codex_home").mkdir()
    shutil.copy2(CODEX_AUTH, result / "codex_home" / "auth.json")
    os.chmod(result / "codex_home" / "auth.json", 0o600)

    container = docker_start(args.arm, workspace, result)
    prompt = (HARNESS / "prompt.txt").read_text()
    codex_command = [
        "docker",
        "exec",
        "--interactive",
        "--user",
        "root",
        container,
        "sudo",
        "-n",
        "--preserve-env",
        "-u",
        "qianl",
        "--",
        "env",
        "HOME=/home/qianl",
        "CODEX_HOME=/home/qianl/.codex-ab",
        "PYTHONDONTWRITEBYTECODE=1",
        "REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt",
        "/usr/local/bin/codex",
        "-m",
        "gpt-6-astra",
        "-c",
        'model_reasoning_effort="xhigh"',
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
        "--json",
        "--output-schema",
        "/experiment/final_schema.json",
        "--output-last-message",
        "/results/final.json",
        "-C",
        "/workspaces/isaaclab_arena",
        "--add-dir",
        "/results",
        "-",
    ]
    started_ns = time.monotonic_ns()
    return_code = None
    try:
        with (result / "codex.jsonl").open("w") as stdout, (result / "codex.stderr.log").open("w") as stderr:
            process = subprocess.Popen(
                codex_command,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                text=True,
            )
            assert process.stdin is not None
            process.stdin.write(prompt)
            process.stdin.close()
            try:
                return_code = process.wait(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                return_code = 124
    finally:
        ended_ns = time.monotonic_ns()
        subprocess.run(["docker", "rm", "--force", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    shutil.copy2(workspace / TARGET, result / "final_environment.yaml")
    changes = workspace_changes(args.arm, workspace)
    run_record = {
        "arm": args.arm,
        "return_code": return_code,
        "started_monotonic_ns": started_ns,
        "ended_monotonic_ns": ended_ns,
        "wall_seconds": (ended_ns - started_ns) / 1e9,
        "workspace_changes": changes,
    }
    (result / "run_record.json").write_text(json.dumps(run_record, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
