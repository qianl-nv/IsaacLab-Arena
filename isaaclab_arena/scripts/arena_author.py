# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Send one authoring command to a long-lived SimApp sidecar and print JSON."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from isaaclab_arena.agentic_environment_generation.simapp.client import (
    SimAppClient,
    SimAppError,
    spawn_simapp_process,
    stop_simapp_process,
    wait_for_simapp_socket,
)
from isaaclab_arena.agentic_environment_generation.simapp.report import (
    AuthoringReport,
    artifact_record,
    validated_output_dir,
    write_report,
)
from isaaclab_arena.agentic_environment_generation.spec_io import safe_filename_stem


def _default_socket_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    checkout_id = hashlib.sha256(str(repo_root).encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"arena_author_{os.getuid()}_{checkout_id}.sock"


def _json_stdout(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True), flush=True)


def _connect(socket_path: Path) -> SimAppClient | None:
    try:
        client = SimAppClient.connect(str(socket_path))
    except OSError:
        return None
    if client.ping():
        return client
    client.disconnect()
    return None


@contextmanager
def _managed_client(socket_path: Path, runtime_log_path: Path) -> Iterator[SimAppClient]:
    client = _connect(socket_path)
    proc = None
    owns_sidecar = client is None
    if owns_sidecar:
        try:
            proc = spawn_simapp_process(str(socket_path), runtime_log_path=str(runtime_log_path))
            wait_for_simapp_socket(str(socket_path), proc)
            client = SimAppClient.connect(str(socket_path))
        except Exception:
            stop_simapp_process(proc, str(socket_path))
            raise
    assert client is not None
    try:
        yield client
    finally:
        if owns_sidecar:
            client.disconnect()
            stop_simapp_process(proc, str(socket_path))
        else:
            client.disconnect()


def _serve(args: argparse.Namespace) -> int:
    from isaaclab_arena.agentic_environment_generation.simapp.server import _serve_socket

    result = _serve_socket(str(args.socket), str(args.runtime_log) if args.runtime_log else None)
    _json_stdout({"command": "sim serve", "status": "completed", "exit_code": result})
    return result


def _status(args: argparse.Namespace) -> int:
    client = _connect(args.socket)
    if client is None:
        _json_stdout({"command": "sim status", "status": "unavailable", "socket": str(args.socket)})
        return 1
    try:
        capabilities = client.capabilities()
    finally:
        client.disconnect()
    _json_stdout({
        "command": "sim status",
        "status": "ready",
        "socket": str(args.socket),
        "capabilities": capabilities.get("result", {}),
    })
    return 0


def _stop(args: argparse.Namespace) -> int:
    client = _connect(args.socket)
    if client is None:
        _json_stdout({"command": "sim stop", "status": "unavailable", "socket": str(args.socket)})
        return 1
    client.shutdown()
    _json_stdout({"command": "sim stop", "status": "completed", "socket": str(args.socket)})
    return 0


def _run_snapshot(args: argparse.Namespace) -> int:
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    output_dir = validated_output_dir(args.output)
    runtime_log = output_dir / "runtime.log"
    started_at = time.monotonic()
    report = AuthoringReport(
        command="graph snapshot",
        status="incomplete",
        inputs={"env_spec": str(args.env_spec.resolve())},
        effective_configuration={"background_panorama": args.background_panorama},
    )
    try:
        spec = ArenaEnvGraphSpec.from_yaml(args.env_spec)
        with _managed_client(args.socket, runtime_log) as client:
            images, dimensions = client.render_spec(spec, background_panorama=args.background_panorama)
        for node_id, image in sorted(images.items()):
            image_path = output_dir / f"{safe_filename_stem(node_id)}.png"
            image_path.write_bytes(image)
            report.artifacts.append(artifact_record(image_path, output_dir))
        report.effective_configuration["aabb_dimensions_m"] = dimensions
        report.status = "completed"
    except Exception as exc:
        report.status = "failed"
        report.error_code = type(exc).__name__
        report.error = str(exc)
    report.timings_s["total"] = time.monotonic() - started_at
    write_report(report, output_dir)
    _json_stdout(report.model_dump(mode="json"))
    return 0 if report.status == "completed" else 1


def _run_preview(args: argparse.Namespace) -> int:
    output_dir = validated_output_dir(args.output)
    runtime_log = output_dir / "runtime.log"
    started_at = time.monotonic()
    report = AuthoringReport(
        command="graph preview",
        status="incomplete",
        inputs={"env_spec": str(args.env_spec.resolve())},
        effective_configuration={
            "num_envs": args.num_envs,
            "num_steps": args.num_steps,
            "env_spacing": args.env_spacing,
        },
    )
    try:
        yaml_text = args.env_spec.read_text(encoding="utf-8")
        with _managed_client(args.socket, runtime_log) as client:
            response = client.run_sim_preview(
                yaml_text,
                num_envs=args.num_envs,
                num_steps=args.num_steps,
                env_spacing=args.env_spacing,
            )
        video_path = Path(response["video_path"])
        output_video = output_dir / "preview.mp4"
        shutil.copy2(video_path, output_video)
        with contextlib.suppress(OSError):
            video_path.unlink()
        report.artifacts.append(artifact_record(output_video, output_dir))
        report.status = "completed"
    except Exception as exc:
        report.status = "failed"
        report.error_code = type(exc).__name__
        report.error = str(exc)
    report.timings_s["total"] = time.monotonic() - started_at
    write_report(report, output_dir)
    _json_stdout(report.model_dump(mode="json"))
    return 0 if report.status == "completed" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, default=_default_socket_path())
    subparsers = parser.add_subparsers(dest="group", required=True)

    sim_parser = subparsers.add_parser("sim", help="Manage the long-lived SimApp sidecar.")
    sim_commands = sim_parser.add_subparsers(dest="command", required=True)
    serve = sim_commands.add_parser("serve", help="Run the SimApp sidecar in the foreground.")
    serve.add_argument("--runtime-log", type=Path, default=None)
    serve.set_defaults(handler=_serve)
    status = sim_commands.add_parser("status", help="Check sidecar health and capabilities.")
    status.set_defaults(handler=_status)
    stop = sim_commands.add_parser("stop", help="Shut down the sidecar.")
    stop.set_defaults(handler=_stop)

    graph_parser = subparsers.add_parser("graph", help="Render or simulate an environment graph.")
    graph_commands = graph_parser.add_subparsers(dest="command", required=True)
    snapshot = graph_commands.add_parser("snapshot", help="Render graph assets and references.")
    snapshot.add_argument("--env-spec", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.add_argument("--background-panorama", action="store_true")
    snapshot.set_defaults(handler=_run_snapshot)
    preview = graph_commands.add_parser("preview", help="Run a bounded zero-action viewport preview.")
    preview.add_argument("--env-spec", type=Path, required=True)
    preview.add_argument("--output", type=Path, required=True)
    preview.add_argument("--num-envs", type=int, default=1)
    preview.add_argument("--num-steps", type=int, default=20)
    preview.add_argument("--env-spacing", type=float, default=3.0)
    preview.set_defaults(handler=_run_preview)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return int(args.handler(args))
    except (AssertionError, OSError, SimAppError, ValueError) as exc:
        _json_stdout({
            "command": " ".join(part for part in (args.group, args.command) if part),
            "status": "failed",
            "error_code": type(exc).__name__,
            "error": str(exc),
        })
        return 1


if __name__ == "__main__":
    sys.exit(main())
