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


def _load_yaml_mapping(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    import yaml

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"Expected a YAML mapping in {path}"
    return value


def _run_asset_inspect(args: argparse.Namespace) -> int:
    output_dir = validated_output_dir(args.output)
    runtime_log = output_dir / "runtime.log"
    started_at = time.monotonic()
    report = AuthoringReport(
        command="asset inspect",
        status="incomplete",
        inputs={"usd": args.usd},
        effective_configuration={"variants": _load_yaml_mapping(args.variants)},
    )
    try:
        with _managed_client(args.socket, runtime_log) as client:
            response = client.inspect_asset(args.usd, variants=report.effective_configuration["variants"])
        result_path = output_dir / "inspection.json"
        result_path.write_text(json.dumps(response["result"], indent=2) + "\n", encoding="utf-8")
        report.artifacts.append(artifact_record(result_path, output_dir))
        report.status = "completed" if response["result"]["topology"]["compatible"] else "incomplete"
    except Exception as exc:
        report.status = "failed"
        report.error_code = type(exc).__name__
        report.error = str(exc)
    report.timings_s["total"] = time.monotonic() - started_at
    write_report(report, output_dir)
    _json_stdout(report.model_dump(mode="json"))
    return 0 if report.status in ("completed", "incomplete") else 1


def _run_asset_probe(args: argparse.Namespace) -> int:
    output_dir = validated_output_dir(args.output)
    runtime_log = output_dir / "runtime.log"
    started_at = time.monotonic()
    report = AuthoringReport(
        command="asset probe",
        status="incomplete",
        inputs={"env_spec": str(args.env_spec.resolve()), "object_name": args.object},
        effective_configuration={"num_steps": args.num_steps, "env_spacing": args.env_spacing},
    )
    try:
        with _managed_client(args.socket, runtime_log) as client:
            response = client.probe_asset(
                args.env_spec.read_text(encoding="utf-8"),
                object_name=args.object,
                num_steps=args.num_steps,
                env_spacing=args.env_spacing,
            )
        result_path = output_dir / "probe.json"
        result_path.write_text(json.dumps(response["result"], indent=2) + "\n", encoding="utf-8")
        report.artifacts.append(artifact_record(result_path, output_dir))
        report.status = "completed"
    except Exception as exc:
        report.status = "failed"
        report.error_code = type(exc).__name__
        report.error = str(exc)
    report.timings_s["total"] = time.monotonic() - started_at
    write_report(report, output_dir)
    _json_stdout(report.model_dump(mode="json"))
    return 0 if report.status == "completed" else 1


def _run_scene_check(args: argparse.Namespace) -> int:
    output_dir = validated_output_dir(args.output)
    runtime_log = output_dir / "runtime.log"
    started_at = time.monotonic()
    configuration = _load_yaml_mapping(args.config)
    report = AuthoringReport(
        command="scene check",
        status="incomplete",
        inputs={"env_spec": str(args.env_spec.resolve())},
        effective_configuration={"mode": args.mode, **configuration},
    )
    try:
        with _managed_client(args.socket, runtime_log) as client:
            response = client.check_scene(
                args.env_spec.read_text(encoding="utf-8"),
                output_path=str(output_dir),
                mode=args.mode,
                configuration=configuration,
            )
        result = response["result"]
        result_path = output_dir / "scene_check.json"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        report.artifacts.append(artifact_record(result_path, output_dir))
        placements_path = result.get("placements_path")
        if placements_path and Path(placements_path).is_file():
            report.artifacts.append(artifact_record(placements_path, output_dir))
        report.status = result.get("status", "completed")
    except Exception as exc:
        report.status = "failed"
        report.error_code = type(exc).__name__
        report.error = str(exc)
    report.timings_s["total"] = time.monotonic() - started_at
    write_report(report, output_dir)
    _json_stdout(report.model_dump(mode="json"))
    return 0 if report.status in ("completed", "incomplete", "unsupported") else 1


def _run_evidence_capture(args: argparse.Namespace) -> int:
    output_dir = validated_output_dir(args.output)
    runtime_log = output_dir / "runtime.log"
    started_at = time.monotonic()
    report = AuthoringReport(
        command="evidence capture",
        status="incomplete",
        inputs={"env_spec": str(args.env_spec.resolve())},
        effective_configuration={
            "num_envs": args.num_envs,
            "num_steps": args.num_steps,
            "env_spacing": args.env_spacing,
        },
    )
    try:
        with _managed_client(args.socket, runtime_log) as client:
            response = client.capture_evidence(
                args.env_spec.read_text(encoding="utf-8"),
                num_envs=args.num_envs,
                num_steps=args.num_steps,
                env_spacing=args.env_spacing,
            )
        result = response["result"]
        video_path = Path(result["video_path"])
        output_video = output_dir / "evidence.mp4"
        shutil.copy2(video_path, output_video)
        with contextlib.suppress(OSError):
            video_path.unlink()
        metadata_path = output_dir / "evidence.json"
        metadata_path.write_text(json.dumps(result["capture"], indent=2) + "\n", encoding="utf-8")
        report.artifacts.extend([
            artifact_record(output_video, output_dir),
            artifact_record(metadata_path, output_dir),
        ])
        camera_status = result["capture"]["camera_metadata"]["status"]
        report.status = "completed" if camera_status == "completed" else "incomplete"
    except Exception as exc:
        report.status = "failed"
        report.error_code = type(exc).__name__
        report.error = str(exc)
    report.timings_s["total"] = time.monotonic() - started_at
    write_report(report, output_dir)
    _json_stdout(report.model_dump(mode="json"))
    return 0 if report.status in ("completed", "incomplete") else 1


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    commands = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        assert isinstance(value, dict), f"{path}:{line_number} must contain a JSON object."
        commands.append(value)
    assert commands, f"No commands found in {path}."
    return commands


def _run_force(args: argparse.Namespace) -> int:
    output_dir = validated_output_dir(args.output)
    started_at = time.monotonic()
    report = AuthoringReport(
        command="force run",
        status="incomplete",
        inputs={"env_spec": str(args.env_spec.resolve()), "commands": str(args.commands.resolve())},
    )
    try:
        with _managed_client(args.socket, output_dir / "runtime.log") as client:
            response = client.run_force(
                args.env_spec.read_text(encoding="utf-8"),
                _load_jsonl(args.commands),
            )
        result = response["result"]
        result_path = output_dir / "force_run.json"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        report.artifacts.append(artifact_record(result_path, output_dir))
        report.status = result["status"]
    except Exception as exc:
        report.status = "failed"
        report.error_code = type(exc).__name__
        report.error = str(exc)
    report.timings_s["total"] = time.monotonic() - started_at
    write_report(report, output_dir)
    _json_stdout(report.model_dump(mode="json"))
    return 0 if report.status == "completed" else 1


def _existing_client(socket_path: Path) -> SimAppClient:
    client = _connect(socket_path)
    if client is None:
        raise SimAppError("A force session requires a persistent sidecar; run `arena_author.py sim serve` first.")
    return client


def _serve_force(args: argparse.Namespace) -> int:
    client = _existing_client(args.socket)
    try:
        response = client.start_force_session(args.env_spec.read_text(encoding="utf-8"))
    finally:
        client.disconnect()
    _json_stdout({"command": "force serve", "status": "completed", **response["result"]})
    return 0


def _send_force_command(args: argparse.Namespace) -> int:
    if args.command_json is not None:
        command = json.loads(args.command_json)
    else:
        command = json.loads(args.command_file.read_text(encoding="utf-8"))
    assert isinstance(command, dict), "The force command must be a JSON object."
    client = _existing_client(args.socket)
    try:
        response = client.force_command(args.session, command)
    finally:
        client.disconnect()
    acknowledgement = response["result"]["acknowledgement"]
    _json_stdout({"command": "force command", **acknowledgement})
    return 0 if acknowledgement["status"] == "completed" else 1


def _finish_force(args: argparse.Namespace) -> int:
    client = _existing_client(args.socket)
    try:
        response = client.finish_force_session(args.session)
    finally:
        client.disconnect()
    _json_stdout({"command": "force finish", "status": "completed", **response["result"]})
    return 0


def _run_task_check(args: argparse.Namespace) -> int:
    output_dir = validated_output_dir(args.output)
    started_at = time.monotonic()
    report = AuthoringReport(
        command="task check",
        status="incomplete",
        inputs={"env_spec": str(args.env_spec.resolve()), "scenarios": str(args.scenarios.resolve())},
    )
    try:
        scenario_document = _load_yaml_mapping(args.scenarios)
        scenarios = scenario_document.get("scenarios")
        assert isinstance(scenarios, list), f"{args.scenarios} must contain a scenarios list."
        with _managed_client(args.socket, output_dir / "runtime.log") as client:
            response = client.check_task(args.env_spec.read_text(encoding="utf-8"), scenarios)
        result = response["result"]
        result_path = output_dir / "task_check.json"
        result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        report.artifacts.append(artifact_record(result_path, output_dir))
        report.status = result["status"]
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

    asset_parser = subparsers.add_parser("asset", help="Inspect or probe asset physics.")
    asset_commands = asset_parser.add_subparsers(dest="command", required=True)
    inspect = asset_commands.add_parser("inspect", help="Inspect authored USD physics.")
    inspect.add_argument("--usd", required=True)
    inspect.add_argument("--variants", type=Path, default=None, help="Optional YAML mapping of USD variants.")
    inspect.add_argument("--output", type=Path, required=True)
    inspect.set_defaults(handler=_run_asset_inspect)
    probe = asset_commands.add_parser("probe", help="Probe one object in a spawned graph scene.")
    probe.add_argument("--env-spec", type=Path, required=True)
    probe.add_argument("--object", required=True)
    probe.add_argument("--num-steps", type=int, default=30)
    probe.add_argument("--env-spacing", type=float, default=3.0)
    probe.add_argument("--output", type=Path, required=True)
    probe.set_defaults(handler=_run_asset_probe)

    scene_parser = subparsers.add_parser("scene", help="Run scene and placement checks.")
    scene_commands = scene_parser.add_subparsers(dest="command", required=True)
    check = scene_commands.add_parser("check", help="Check sampled, pooled, or static scene state.")
    check.add_argument("--env-spec", type=Path, required=True)
    check.add_argument("--config", type=Path, default=None)
    check.add_argument("--mode", choices=("sampled", "pool", "static"), default="sampled")
    check.add_argument("--output", type=Path, required=True)
    check.set_defaults(handler=_run_scene_check)

    evidence_parser = subparsers.add_parser("evidence", help="Capture viewport evidence.")
    evidence_commands = evidence_parser.add_subparsers(dest="command", required=True)
    capture = evidence_commands.add_parser("capture", help="Capture bounded preview evidence.")
    capture.add_argument("--env-spec", type=Path, required=True)
    capture.add_argument("--num-envs", type=int, default=1)
    capture.add_argument("--num-steps", type=int, default=20)
    capture.add_argument("--env-spacing", type=float, default=3.0)
    capture.add_argument("--output", type=Path, required=True)
    capture.set_defaults(handler=_run_evidence_capture)

    force_parser = subparsers.add_parser("force", help="Run bounded physical-force commands.")
    force_commands = force_parser.add_subparsers(dest="command", required=True)
    force_run = force_commands.add_parser("run", help="Run a finite JSONL command sequence.")
    force_run.add_argument("--env-spec", type=Path, required=True)
    force_run.add_argument("--commands", type=Path, required=True)
    force_run.add_argument("--output", type=Path, required=True)
    force_run.set_defaults(handler=_run_force)
    force_serve = force_commands.add_parser("serve", help="Create a session on a persistent sidecar.")
    force_serve.add_argument("--env-spec", type=Path, required=True)
    force_serve.set_defaults(handler=_serve_force)
    force_command = force_commands.add_parser("command", help="Send one command to an active session.")
    force_command.add_argument("--session", required=True)
    command_source = force_command.add_mutually_exclusive_group(required=True)
    command_source.add_argument("--command-json")
    command_source.add_argument("--command-file", type=Path)
    force_command.set_defaults(handler=_send_force_command)
    force_finish = force_commands.add_parser("finish", help="Close a force session.")
    force_finish.add_argument("--session", required=True)
    force_finish.set_defaults(handler=_finish_force)

    task_parser = subparsers.add_parser("task", help="Check task semantics in isolated scenarios.")
    task_commands = task_parser.add_subparsers(dest="command", required=True)
    task_check = task_commands.add_parser("check", help="Run task scenario checks.")
    task_check.add_argument("--env-spec", type=Path, required=True)
    task_check.add_argument("--scenarios", type=Path, required=True)
    task_check.add_argument("--output", type=Path, required=True)
    task_check.set_defaults(handler=_run_task_check)
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
