# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Long-lived SimulationApp server for the review GUI (Unix socket JSON-RPC)."""

from __future__ import annotations

import argparse
import contextlib
import json
import signal
import socket
import sys
import traceback
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from pydantic import ValidationError

from isaaclab_arena.agentic_environment_generation.simapp.boot import launch_simulation_app
from isaaclab_arena.agentic_environment_generation.simapp.protocol import (
    MAX_REQUEST_BYTES,
    PROTOCOL_VERSION,
    CancelJobRequest,
    CapabilitiesRequest,
    CaptureEvidenceRequest,
    CheckTaskRequest,
    FinishForceSessionRequest,
    ForceCommandRequest,
    InspectAssetRequest,
    JobOperation,
    JobResultRequest,
    JobStatusRequest,
    PingRequest,
    ProbeAssetRequest,
    RenderSpecRequest,
    RunForceRequest,
    RunSimPreviewRequest,
    SceneCheckRequest,
    ShutdownRequest,
    StartForceSessionRequest,
    SubmitJobRequest,
    parse_request,
    response_dict,
)
from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

_RUNTIME_LOG_PATH: Path | None = None


@dataclass
class _Job:
    """One queued, single-flight SimApp operation."""

    operation: JobOperation
    state: str = "pending"
    result: dict[str, Any] | None = None
    error: str | None = None


def _log_current_exception() -> None:
    """Write the active traceback to stderr and the sidecar runtime log."""
    text = traceback.format_exc()
    print(text, file=sys.stderr, end="")
    if _RUNTIME_LOG_PATH is not None:
        with _RUNTIME_LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(text)


def _install_signal_handlers() -> None:
    def _exit(signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _exit)
    signal.signal(signal.SIGINT, _exit)


def _write_response(writer: TextIO, payload: dict[str, Any]) -> None:
    writer.write(json.dumps(payload) + "\n")
    writer.flush()


def _handle_force_session_request(req, writer: TextIO, app, force_sessions: dict[str, Any]) -> None:
    """Handle one stateful force-session lifecycle request."""
    if isinstance(req, StartForceSessionRequest):
        if force_sessions:
            _write_response(
                writer,
                response_dict(
                    req,
                    error_code="SESSION_BUSY",
                    error="Only one active force session is supported.",
                ),
            )
            return
        from isaaclab_arena.agentic_environment_generation.force.runtime import ForceSession

        session_id = uuid4().hex
        try:
            force_sessions[session_id] = ForceSession(app, req.yaml_text)
        except Exception as exc:
            _log_current_exception()
            _write_response(writer, response_dict(req, error_code="SESSION_START_FAILED", error=str(exc)))
        else:
            _write_response(
                writer,
                response_dict(req, result={"session_id": session_id, "state": "ready"}),
            )
        return

    session = force_sessions.get(req.session_id)
    if session is None:
        _write_response(
            writer,
            response_dict(
                req,
                error_code="SESSION_NOT_FOUND",
                error=f"Unknown force session: {req.session_id}",
            ),
        )
        return
    if isinstance(req, ForceCommandRequest):
        acknowledgement = session.execute(req.command)
        _write_response(writer, response_dict(req, result={"acknowledgement": acknowledgement}))
        return

    assert isinstance(req, FinishForceSessionRequest)
    force_sessions.pop(req.session_id)
    try:
        final_state = session.controller.inspect()
    finally:
        session.close()
    _write_response(
        writer,
        response_dict(req, result={"session_id": req.session_id, "state": "closed", "final_state": final_state}),
    )


def _serve_connection(
    reader: TextIO,
    writer: TextIO,
    *,
    app,
    render_fn,
    spec_cls,
    jobs: dict[str, _Job],
    force_sessions: dict[str, Any],
) -> bool:
    """Handle JSON-RPC requests until disconnect; return True after ``shutdown``."""
    while raw_line := reader.readline(MAX_REQUEST_BYTES + 1):
        if len(raw_line) > MAX_REQUEST_BYTES:
            _write_response(
                writer,
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": "invalid",
                    "ok": False,
                    "error_code": "REQUEST_TOO_LARGE",
                    "error": f"request exceeds {MAX_REQUEST_BYTES} bytes",
                },
            )
            continue
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            _write_response(
                writer,
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": "invalid",
                    "ok": False,
                    "error_code": "INVALID_JSON",
                    "error": f"bad json: {exc}",
                },
            )
            continue

        try:
            req = parse_request(payload)
        except ValidationError as exc:
            _write_response(
                writer,
                {
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": str(payload.get("request_id", "invalid")),
                    "ok": False,
                    "error_code": "INVALID_REQUEST",
                    "error": str(exc),
                },
            )
            continue

        if isinstance(req, ShutdownRequest):
            for session in force_sessions.values():
                session.close()
            force_sessions.clear()
            _write_response(writer, response_dict(req))
            return True

        if isinstance(req, PingRequest):
            _write_response(writer, response_dict(req))
            continue

        if isinstance(req, CapabilitiesRequest):
            _write_response(
                writer,
                response_dict(
                    req,
                    result={
                        "commands": [
                            "ping",
                            "shutdown",
                            "capabilities",
                            "render_spec",
                            "run_sim_preview",
                            "inspect_asset",
                            "probe_asset",
                            "check_scene",
                            "capture_evidence",
                            "run_force",
                            "start_force_session",
                            "force_command",
                            "finish_force_session",
                            "check_task",
                            "submit",
                            "status",
                            "result",
                            "cancel",
                        ],
                        "job_operations": [
                            "render_spec",
                            "run_sim_preview",
                            "probe_asset",
                            "check_scene",
                            "capture_evidence",
                            "run_force",
                            "check_task",
                        ],
                        "single_flight": True,
                    },
                ),
            )
            continue

        if isinstance(req, (StartForceSessionRequest, ForceCommandRequest, FinishForceSessionRequest)):
            _handle_force_session_request(req, writer, app, force_sessions)
            continue

        if isinstance(req, SubmitJobRequest):
            if force_sessions:
                _write_response(
                    writer,
                    response_dict(req, error_code="SESSION_BUSY", error="Finish the active force session first."),
                )
                continue
            job_id = uuid4().hex
            jobs[job_id] = _Job(req.operation)
            _write_response(writer, response_dict(req, result={"job_id": job_id, "state": "pending"}))
            continue

        if isinstance(req, JobStatusRequest):
            job = jobs.get(req.job_id)
            if job is None:
                _write_response(
                    writer,
                    response_dict(req, error_code="JOB_NOT_FOUND", error=f"unknown job: {req.job_id}"),
                )
            else:
                _write_response(writer, response_dict(req, result={"job_id": req.job_id, "state": job.state}))
            continue

        if isinstance(req, CancelJobRequest):
            job = jobs.get(req.job_id)
            if job is None:
                _write_response(
                    writer,
                    response_dict(req, error_code="JOB_NOT_FOUND", error=f"unknown job: {req.job_id}"),
                )
            elif job.state != "pending":
                _write_response(
                    writer,
                    response_dict(
                        req,
                        error_code="JOB_NOT_CANCELLABLE",
                        error=f"job is already {job.state}",
                    ),
                )
            else:
                job.state = "cancelled"
                _write_response(writer, response_dict(req, result={"job_id": req.job_id, "state": job.state}))
            continue

        if isinstance(req, JobResultRequest):
            job = jobs.get(req.job_id)
            if job is None:
                _write_response(
                    writer,
                    response_dict(req, error_code="JOB_NOT_FOUND", error=f"unknown job: {req.job_id}"),
                )
                continue
            if job.state == "cancelled":
                _write_response(
                    writer,
                    response_dict(req, error_code="JOB_CANCELLED", error=f"job was cancelled: {req.job_id}"),
                )
                continue
            if job.state == "pending":
                job.state = "running"
                try:
                    job.result = _execute_operation(app, job.operation, render_fn, spec_cls)
                except Exception as exc:
                    _log_current_exception()
                    job.error = str(exc)
                    job.state = "failed"
                else:
                    job.state = "completed"
            if job.state == "failed":
                _write_response(
                    writer,
                    response_dict(req, error_code="JOB_FAILED", error=job.error or "job failed"),
                )
            else:
                _write_response(
                    writer,
                    response_dict(
                        req,
                        result={"job_id": req.job_id, "state": job.state, "operation_result": job.result},
                    ),
                )
            continue

        try:
            if force_sessions:
                raise RuntimeError("Finish the active force session before running another simulation operation.")
            result = _execute_operation(app, req, render_fn, spec_cls)
        except Exception as exc:
            _log_current_exception()
            _write_response(writer, response_dict(req, error_code="COMMAND_FAILED", error=str(exc)))
        else:
            _write_response(writer, response_dict(req, result=result))

    return False


def _execute_operation(app, req: JobOperation, render_fn, spec_cls) -> dict[str, Any]:
    """Execute one validated simulation operation."""
    if isinstance(req, InspectAssetRequest):
        from isaaclab_arena.agentic_environment_generation.simapp.asset_inspection import inspect_usd_asset

        return inspect_usd_asset(req.usd_path, variants=req.variants)
    if isinstance(req, RenderSpecRequest):
        return _handle_render_spec(app, req, render_fn, spec_cls)
    if isinstance(req, RunSimPreviewRequest):
        return _handle_run_sim_preview(app, req)
    if isinstance(req, ProbeAssetRequest):
        from isaaclab_arena.agentic_environment_generation.simapp.runtime_probe import probe_graph_object

        return probe_graph_object(
            app,
            req.yaml_text,
            object_name=req.object_name,
            num_steps=req.num_steps,
            env_spacing=req.env_spacing,
        )
    if isinstance(req, SceneCheckRequest):
        from isaaclab_arena.agentic_environment_generation.simapp.scene_check import check_graph_scene

        return check_graph_scene(
            app,
            req.yaml_text,
            output_path=req.output_path,
            mode=req.mode,
            configuration=req.configuration,
        )
    if isinstance(req, CaptureEvidenceRequest):
        from isaaclab_arena.agentic_environment_generation.simapp.evidence import capture_graph_evidence

        return capture_graph_evidence(
            app,
            req.yaml_text,
            num_envs=req.num_envs,
            num_steps=req.num_steps,
            env_spacing=req.env_spacing,
        )
    if isinstance(req, RunForceRequest):
        from isaaclab_arena.agentic_environment_generation.force.runtime import run_force_commands

        return run_force_commands(app, req.yaml_text, req.commands)
    if isinstance(req, CheckTaskRequest):
        from isaaclab_arena.agentic_environment_generation.force.runtime import check_task_scenarios

        return check_task_scenarios(app, req.yaml_text, req.scenarios)
    raise TypeError(f"unsupported operation: {type(req).__name__}")


def _serve_socket(socket_path: str, runtime_log_path: str | None = None) -> int:
    """Boot SimApp, bind ``socket_path``, and service requests sequentially."""
    global _RUNTIME_LOG_PATH

    _install_signal_handlers()
    _RUNTIME_LOG_PATH = Path(runtime_log_path) if runtime_log_path else Path(socket_path).with_suffix(".log")
    _RUNTIME_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    app = launch_simulation_app()
    if app is None:
        print("[simapp] SimulationApp launch returned None", file=sys.stderr)
        return 1

    # Kit/Omniverse and pxr must load only after SimulationApp starts.
    from isaaclab_arena.agentic_environment_generation.simapp.thumbnail_capture import (  # noqa: PLC0415
        render_thumbnails_with_app,
    )

    path = Path(socket_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(5)
    print(f"[simapp] listening on {path}", file=sys.stderr)
    jobs: dict[str, _Job] = {}
    force_sessions: dict[str, Any] = {}

    try:
        while True:
            conn, _ = server.accept()
            with conn:
                reader = conn.makefile("r", encoding="utf-8", newline="\n")
                writer = conn.makefile("w", encoding="utf-8", newline="\n")
                try:
                    should_exit = _serve_connection(
                        reader,
                        writer,
                        app=app,
                        render_fn=render_thumbnails_with_app,
                        spec_cls=ArenaEnvGraphSpec,
                        jobs=jobs,
                        force_sessions=force_sessions,
                    )
                finally:
                    reader.close()
                    writer.close()
                if should_exit:
                    break
    finally:
        for session in force_sessions.values():
            with contextlib.suppress(Exception):
                session.close()
        server.close()
        path.unlink(missing_ok=True)
        with contextlib.suppress(Exception):
            app.close()

    return 0


def _handle_render_spec(
    app,
    req: RenderSpecRequest,
    render_fn,
    spec_cls,
) -> dict[str, Any]:
    """Parse the spec, run thumbnail rendering, marshal the response."""
    try:
        spec = spec_cls.from_dict(yaml.safe_load(req.yaml_text))
    except Exception as exc:
        raise ValueError(f"spec parse failed: {exc}") from exc

    try:
        paths, aabb_dimensions_m = render_fn(app, spec, background_panorama=req.background_panorama)
    except Exception as exc:
        raise RuntimeError(f"render failed: {exc}") from exc

    return {
        "paths": {node_id: str(p) for node_id, p in paths.items()},
        "aabb_dimensions_m": {node_id: list(dims) for node_id, dims in aabb_dimensions_m.items()},
    }


def _handle_run_sim_preview(app, req: RunSimPreviewRequest) -> dict[str, Any]:
    """Handle run_sim_preview JSON-RPC."""
    from isaaclab_arena.agentic_environment_generation.simapp.sim_preview import run_sim_preview  # noqa: PLC0415

    try:
        return run_sim_preview(
            app,
            req.yaml_text,
            num_envs=req.num_envs,
            num_steps=req.num_steps,
            env_spacing=req.env_spacing,
        )
    except Exception as exc:
        raise RuntimeError(f"sim preview failed: {exc}") from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--socket",
        required=True,
        help="Unix domain socket path for newline-delimited JSON-RPC requests.",
    )
    parser.add_argument(
        "--runtime-log",
        default=None,
        help="Traceback log path (default: the socket path with a .log suffix).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    return _serve_socket(args.socket, args.runtime_log)


if __name__ == "__main__":
    sys.exit(main())
