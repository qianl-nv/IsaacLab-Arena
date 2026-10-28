# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Render a seven-chapter authoring retrospective from saved YAML and simulation media."""

import argparse
import hashlib
import html
import json
import shutil
import subprocess
import tempfile
import yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT = Path(__file__).resolve().parent
MEDIA = ROOT / "docs/images/workbench_cleanup"
WIDTH, HEIGHT, FPS = 1920, 1080, 20
CHAPTER_SECONDS = 12
ACCENT = "#86e4bd"
BLUE = "#80baff"
AMBER = "#f3cd85"

CHAPTERS = [
    {
        "title": "Inspect assets and choose usable parts",
        "short": "Inspect assets",
        "action": "Search SimReady Central. Inspect rigid bodies, joints, bounds, and physics variants.",
        "rationale": "A visible component is not always movable. Check its physics before defining a task.",
        "result": (
            "Four drawer joints and a hinged case. Blue bins are fused; the separate gray D00814 bin is pickable."
        ),
        "file": "scene.yaml · asset registry",
        "code": (
            "background: cleanup_workbench\nobjects:\n  socket_set: cleanup_socket_set\n  overhead_bin:"
            " simready_usd_object\nembodiment: no_embodiment"
        ),
        "images": ["scene.png", "scene.png", "scene.png"],
        "captions": [
            "Selected SimReady assets in the saved scene",
            "Blue bins belong to the workbench mesh",
            "Gray bin: separate movable replacement",
        ],
        "observation": "Capability inspection changes the selection: use an independent bin for the rack-packing task.",
    },
    {
        "title": "Build one shared scene with spatial relations",
        "short": "Place the scene",
        "action": "Write scene.yaml. Name the tabletop, clutter area, top rack, and moving drawer reference.",
        "rationale": "Reuse the same scene for all three tasks. Validate support height and rack edge margins.",
        "result": "Three on relations and five clutter_on relations. The tools form a pile; placement seed is 17.",
        "file": "scene.yaml · relations",
        "code": (
            "- kind: 'on'\n  subject: socket_set\n  reference: tabletop\n- kind: clutter_on\n  subject:"
            " slotted_screwdriver\n  reference: clutter_area"
        ),
        "images": ["scene.png", "task_2/00_start.png", "task_1/00_start.png"],
        "captions": [
            "Shared scene and support surfaces",
            "Five loose tools in the central clutter area",
            "Open case and device ready for separate tasks",
        ],
        "observation": (
            "Support references stay fixed in the placement graph. The drawer reference follows its live articulation"
            " link."
        ),
    },
    {
        "title": "Make collision geometry match usable space",
        "short": "Repair physics",
        "action": (
            "Replace blocked collision shapes. Retain case inserts with fixed joints and preserve visible meshes."
        ),
        "rationale": (
            "The source SDF trapped props in empty-looking space. A hollow drawer needs an open collision interior."
        ),
        "result": "Panel drawer, inset case colliders, convex tool hulls. The socket set is scaled to 90% to fit.",
        "file": "assets.py · physics adapters",
        "code": (
            "cleanup_workbench: open tray panels\ncleanup_socket_set: retained inserts\ncleanup_tool: convex hull"
            " contacts\nscale: [0.9, 0.9, 0.9]\n# source visuals preserved"
        ),
        "images": ["task_1/01_end.png", "task_1/02_end.png", "task_1/03_end.png"],
        "captions": [
            "Saved viewport: top-left drawer opened",
            "Saved viewport: case inside the drawer",
            "Saved viewport: loaded drawer closed",
        ],
        "observation": (
            "These successful viewports illustrate the repaired assets. They are not screenshots of the earlier failed"
            " collider attempts."
        ),
    },
    {
        "title": "Compose three tasks from reusable atomic tasks",
        "short": "Compose tasks",
        "action": "Create task_1.yaml, task_2.yaml, and task_3.yaml. Each includes the same scene.yaml.",
        "rationale": (
            "Reuse door, goal-pose, and button tasks. Extend only the missing containment and plug-withdrawal behavior."
        ),
        "result": "Three sequential task graphs: 4 + 7 + 2 subtasks. Declare which final conditions must remain true.",
        "file": "task_1.yaml · task_2.yaml · task_3.yaml",
        "code": (
            "external_yaml: scene.yaml\ntask:\n  composition: sequential\n  desired_subtask_success_state:\n    [true,"
            " null, true, true]\n# task 1: drawer-open is intermediate"
        ),
        "images": ["task_1/00_start.png", "task_2/00_end.png", "task_3/00_start.png"],
        "captions": [
            "Task 1: close and store the socket set",
            "Task 2: load the movable overhead bin",
            "Task 3: switch off and unplug the device",
        ],
        "observation": (
            "The task graph expresses order. Current final-state checks prevent a completed milestone from hiding a"
            " later failure."
        ),
    },
    {
        "title": "Test with physical forces and inspect each boundary",
        "short": "Force-test",
        "action": "Send JSONL operator commands. Move bodies with bounded wrenches and joints with effort control.",
        "rationale": (
            "Check real motion, contact, containment, and settling under gravity before recording a successful"
            " sequence."
        ),
        "result": (
            "No robot and no pose teleportation during task motion. Capture each subtask start and end: 26 images."
        ),
        "file": "force_demo.py · operator commands",
        "code": (
            '{"action": "move", "name": "socket_set"}\n{"action": "joint", "name": "left_drawers"}\n{"action":'
            ' "release", "name": "socket_set"}\n{"action": "check", "index": 2}\n# schematic command excerpts'
        ),
        "images": ["task_1/02_end.png", "task_2/02_end.png", "task_3/01_end.png"],
        "captions": [
            "Case placement checked after physical motion",
            "Tools released into the bin and checked",
            "Plug withdrawn along the outlet axis",
        ],
        "observation": (
            "The original validation used live command-driven force operation. It was not a human mouse-teleoperation"
            " recording."
        ),
    },
    {
        "title": "Correct failures and audit the final state",
        "short": "Audit success",
        "action": (
            "Diagnose pinned tools, false box corners, and loaded-bin tilt. Rerun after physics and controller fixes."
        ),
        "rationale": (
            "Historical completion alone is insufficient. Every required final condition must still hold at the end."
        ),
        "result": (
            "Recorded result: 3 tasks passed; all 13 subtasks completed. Focused checks: 73 graph tests and 1 predicate"
            " test."
        ),
        "file": "tasks.py · current final conditions",
        "code": (
            "task_success =\n  recorded_sequence_complete\n  AND required_current_conditions\n\n# contact + containment"
            " + settling\n# full test suite was not run"
        ),
        "images": ["task_2/05_end.png", "task_2/06_end.png", "task_3/01_end.png"],
        "captions": [
            "All five tools packed inside the bin",
            "Loaded bin returned to the top rack",
            "Off state and withdrawn plug checked",
        ],
        "observation": (
            "Saved results establish feasibility at the tested seed. They do not establish robot reachability or"
            " all-seed robustness."
        ),
    },
    {
        "title": "Watch the complete, validated workbench demonstration",
        "short": "Final demo",
        "action": "Play the original combined demonstration GIF in full, at its original playback speed.",
        "rationale": "Follow each independent task from its initial scene through its verified final state.",
        "result": (
            "Original recorded outcomes: socket set 4/4; tools and bin 7/7; device 2/2. All three final success checks"
            " passed."
        ),
        "file": "scene.yaml → three sequential task YAMLs",
        "code": (
            "task_1: [true, null, true, true]\ntask_2: [null, true, true, true,\n         true, true, true]\ntask_3:"
            " [true, true]\n# required final-state configuration"
        ),
        "images": [None],
        "captions": ["Original final demo GIF · 2:12 · uncut · 1× speed"],
        "observation": (
            "Saved validation summary, not live telemetry. The cord is visual; button state represents OFF. No"
            " electrical simulation."
        ),
    },
]


def text_svg(x, y, value, size=20, color="#e3ecf7", anchor="middle"):
    """Return one escaped SVG text element."""
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}">{html.escape(value)}</text>'


def graph(chapter, reveal):
    """Draw source-derived scene/task relationships and labeled process diagrams."""
    parts = [
        '<svg viewBox="0 0 640 520" xmlns="http://www.w3.org/2000/svg">',
        (
            '<defs><marker id="arr" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0L7'
            ' 3.5L0 7" fill="#7f96b1"/></marker></defs>'
        ),
    ]

    def node(x, y, w, label, sub="", color=BLUE, group=1, height=62):
        opacity = "1" if group <= reveal else "0.12"
        parts.append(f'<g opacity="{opacity}">')
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{height}" rx="11" fill="#192d44" stroke="{color}"'
            ' stroke-width="1.6"/>'
        )
        parts.append(text_svg(x + w / 2, y + (26 if sub else height / 2 + 7), label, 19, color))
        if sub:
            parts.append(text_svg(x + w / 2, y + 47, sub, 14, "#a3b5c8"))
        parts.append("</g>")

    def edge(x1, y1, x2, y2, label="", group=1, color="#7f96b1"):
        opacity = "1" if group <= reveal else "0.12"
        parts.append(
            f'<g opacity="{opacity}"><path d="M{x1} {y1}L{x2} {y2}" stroke="{color}" stroke-width="2"'
            ' marker-end="url(#arr)"/></g>'
        )
        if label and group <= reveal:
            parts.append(text_svg((x1 + x2) / 2 + 8, (y1 + y2) / 2 - 9, label, 16, color))

    if chapter == 0:
        node(205, 15, 230, "Workbench", "SimReady background")
        for x, title, sub in [
            (15, "Tabletop", "support"),
            (225, "Drawer", "prismatic joint"),
            (435, "Top rack", "support"),
        ]:
            edge(320, 77, x + 95, 151, group=2)
            node(x, 151, 190, title, sub, group=2)
        parts.append(text_svg(320, 125, "parent / component references", 16, "#a3b5c8"))
        node(35, 296, 260, "Socket set", "hinged lid + fitted inserts", group=3)
        node(345, 296, 260, "Gray overhead bin", "independent rigid body", ACCENT, group=3)
        node(35, 409, 260, "Oscilloscope", "pressable button joint", group=3)
        node(345, 409, 260, "5 hand tools", "3 screwdrivers + 2 wrenches", group=3)
    elif chapter == 1:
        node(25, 20, 205, "socket_set", group=1)
        node(25, 130, 205, "oscilloscope", group=2)
        node(395, 76, 220, "tabletop", "fixed layout anchor")
        edge(230, 51, 395, 105, "on", group=1, color=ACCENT)
        edge(230, 161, 395, 115, "on", group=2, color=ACCENT)
        node(25, 260, 205, "overhead_bin", group=2)
        node(395, 260, 220, "top_rack", "edge margin: 0.01 m", group=2)
        edge(230, 291, 395, 291, "on", group=2, color=ACCENT)
        node(25, 390, 205, "5 loose tools", "five distinct relations", AMBER, group=3)
        node(395, 390, 220, "clutter_area", "central release region", group=3)
        edge(230, 421, 395, 421, "clutter_on × 5", group=3, color=AMBER)
        parts.append(text_svg(320, 496, "Arrows: subject → reference · source relations", 16, "#a3b5c8"))
    elif chapter == 2:
        node(185, 10, 270, "Pinned source USD", "visible geometry retained")
        edge(320, 72, 320, 125, "adapt")
        node(185, 125, 270, "Arena physics wrapper", "environment-owned edits", ACCENT)
        for x, label, sub in [
            (15, "Bench / drawer", "separate open panels"),
            (225, "Socket case", "fixed insert joints"),
            (435, "Loose tools", "convex hull contacts"),
        ]:
            edge(320, 187, x + 95, 273, group=2)
            node(x, 273, 190, label, sub, group=2)
        for x in (110, 320, 530):
            edge(x, 335, 320, 425, group=3)
        node(155, 425, 330, "Usable physical workspace", "test fit, motion, and contact", ACCENT, group=3)
    elif chapter in (3, 6):
        parts.append(text_svg(12, 21, "task_1.yaml   /   socket set → drawer", 20, BLUE, "start"))
        for i, label in enumerate(["Close case", "Open drawer", "Insert case", "Close drawer"]):
            node(8 + i * 158, 43, 148, label, color=BLUE, height=54)
            if i < 3:
                edge(156 + i * 158, 70, 166 + i * 158, 70)
        parts.append(text_svg(320, 124, "CloseDoor → OpenDoor → ClosedCaseInDrawer → CloseDoor", 15, "#a3b5c8"))
        if reveal >= 2:
            parts.append(text_svg(12, 184, "task_2.yaml   /   five tools → overhead bin", 20, AMBER, "start"))
        node(12, 206, 190, "Bin to table", "GoalPoseTask", AMBER, group=2)
        node(438, 206, 190, "Bin to rack", "GoalPoseTask", AMBER, group=2)
        edge(107, 268, 107, 300, group=2)
        for i, label in enumerate(["Slotted", "Torx", "Phillips", "Wrench", "Small W."]):
            node(12 + i * 125, 300, 116, label, color=AMBER, group=2, height=46)
            if i < 4:
                edge(128 + i * 125, 323, 137 + i * 125, 323, group=2)
        edge(570, 300, 533, 268, group=2)
        if reveal >= 2:
            parts.append(text_svg(320, 375, "Five sequential ToolInBinTask nodes", 16, "#a3b5c8"))
        if reveal >= 3:
            parts.append(text_svg(12, 427, "task_3.yaml   /   device off → unplug", 20, ACCENT, "start"))
        node(35, 449, 230, "Press power button", "PressButtonTask", ACCENT, group=3)
        node(375, 449, 230, "Withdraw plug", "UnplugTask", ACCENT, group=3)
        edge(265, 480, 375, 480, "then", group=3)
    elif chapter == 4:
        stages = [
            ("JSONL operator", "move / joint / release", 1),
            ("Bounded physical forces", "wrenches + joint efforts", 1),
            ("Physics + contact sensors", "gravity remains enabled", 2),
            ("Task predicates", "containment + contact + settling", 2),
            ("Progress + boundary images", "check each start / end", 3),
        ]
        for i, (label, sub, group) in enumerate(stages):
            node(110, i * 102 + 5, 420, label, sub, ACCENT if i == 4 else BLUE, group)
            if i < 4:
                edge(320, i * 102 + 67, 320, (i + 1) * 102 + 5, group=min(group + 1, 3))
    else:
        node(130, 5, 380, "Historical sequence complete", "milestones have been reached")
        edge(320, 67, 320, 125, "AND", group=2)
        node(130, 125, 380, "Required current conditions", "must remain true at the end", AMBER, group=2)
        for x, label, sub in [
            (12, "Case / drawer", "closed + contained"),
            (225, "Loaded bin", "5 tools + rack pose"),
            (438, "Device / plug", "off + withdrawn"),
        ]:
            edge(320, 187, x + 95, 260, group=2)
            node(x, 260, 190, label, sub, group=2)
        for x in (107, 320, 533):
            edge(x, 322, 320, 410, group=3)
        node(130, 410, 380, "Native Arena success", "all 3 original runs passed", ACCENT, group=3)
        parts.append(text_svg(320, 502, "Audit both history and current state", 17, "#a3b5c8"))
    parts.append("</svg>")
    return "".join(parts)


def render_html(chapter, reveal, demo=False):
    """Build a three-panel chapter frame with progressive graph disclosure."""
    info = CHAPTERS[chapter]
    picture = ""
    if not demo:
        uri = (MEDIA / info["images"][reveal - 1]).as_uri()
        picture = f'<img src="{uri}" alt="Saved simulation viewport">'
    cards = "".join(
        f'<section class="note"><label>{label}</label><p>{html.escape(info[key])}</p></section>'
        for label, key in [("ACTION", "action"), ("DESIGN RATIONALE", "rationale"), ("RECORDED FINDING", "result")]
    )
    steps = "".join(
        f'<div class="step {"active" if i == chapter else "done" if i < chapter else ""}"><b>{i + 1:02d}</b>'
        f' {item["short"]}</div>'
        for i, item in enumerate(CHAPTERS)
    )
    caption = info["captions"][0 if demo else reveal - 1]
    return f"""<!doctype html><html><meta charset="utf-8"><style>
*{{box-sizing:border-box}}body{{margin:0;width:1920px;height:1080px;overflow:hidden;background:#09131f;color:#e3ecf7;font-family:'DejaVu Sans',sans-serif}}
.top{{position:absolute;left:32px;top:24px;right:32px}}.kicker{{font-size:16px;letter-spacing:2px;color:#86e4bd}}h1{{font-size:34px;margin:9px 0 0;font-weight:650}}
.counter{{position:absolute;right:0;top:8px;border:1px solid #31445b;padding:14px 22px;border-radius:12px;font-size:24px;color:#86e4bd}}
.panel{{position:absolute;top:132px;height:854px;background:#101e2e;border:1px solid #283b51;border-radius:18px;padding:24px}}
.agent{{left:32px;width:480px}}.graph{{left:532px;width:688px}}.sim{{left:1240px;width:648px}}
.panel-title{{font-size:16px;letter-spacing:1.4px;color:#a4b8cf;border-bottom:1px solid #2a3b50;padding-bottom:20px}}
.note{{margin-top:24px;border-left:3px solid #3d6287;padding-left:17px}}label{{font-size:14px;letter-spacing:1.6px;color:#86e4bd}}p{{font-size:23px;line-height:1.42;margin:10px 0 0}}
.agent .meta{{position:absolute;bottom:26px;left:25px;right:25px;font-size:16px;line-height:1.5;color:#90a6bf}}
.graph-name{{font-size:16px;margin:19px 0 10px;color:#86e4bd}}svg{{display:block;width:640px;height:520px;font-family:'DejaVu Sans',sans-serif}}
pre{{font-family:'DejaVu Sans Mono',monospace;font-size:17px;line-height:1.48;white-space:pre-wrap;color:#afc8e2;background:#0a1625;border-radius:10px;padding:16px;margin:14px 0 0}}
.sim-kind{{margin-top:27px;color:#86e4bd;font-size:18px}}.viewport{{position:absolute;left:20px;top:164px;width:608px;height:342px;background:#101720;overflow:hidden;border-radius:9px}}
.viewport img{{width:100%;height:100%;object-fit:contain}}.caption{{position:absolute;left:24px;top:526px;width:595px;font-size:20px;line-height:1.4;color:#d1e0f0}}
.observation{{position:absolute;left:24px;top:615px;width:595px;background:#16293a;border-radius:12px;padding:19px;font-size:21px;line-height:1.45}}
.sim-footer{{position:absolute;bottom:26px;left:24px;font-size:16px;color:#90a6bf}}
.timeline{{position:absolute;left:32px;right:32px;top:1010px;display:flex;gap:10px}}.step{{flex:1;border-top:3px solid #24384c;padding-top:12px;font-size:17px;color:#688098}}.step b{{margin-right:8px}}.step.active{{color:#86e4bd;border-color:#86e4bd}}.step.done{{color:#9db1c7;border-color:#466780}}
</style><body><div class="top"><div class="kicker">WORKBENCH CLEANUP / FROM REQUEST TO VALIDATED TASKS</div><h1>{html.escape(info["title"])}</h1><div class="counter">{chapter + 1:02d} / 07</div></div>
<div class="panel agent"><div class="panel-title">AGENT / ACTIONS + TESTS</div>{cards}<div class="meta">Authoring reconstruction from saved evidence.<br>Decision summaries, not a live session transcript.<br>Assets: NVIDIA · ForgeCAD · PalatialSim.</div></div>
<div class="panel graph"><div class="panel-title">ARENA / YAML → GRAPH</div><div class="graph-name">{html.escape(info["file"])}</div>{graph(chapter, reveal)}<pre>{html.escape(info["code"])}</pre></div>
<div class="panel sim"><div class="panel-title">SIMULATION / SAVED VIEWPORT</div><div class="sim-kind">{"FINAL DEMO · ORIGINAL GIF" if demo else "SIMULATION EVIDENCE"}</div><div class="viewport">{picture}</div><div class="caption">{html.escape(caption)}</div><div class="observation">{html.escape(info["observation"])}</div><div class="sim-footer">Isaac Sim · CPU PhysX · no robot embodiment</div></div>
<div class="timeline">{steps}</div></body></html>"""


def screenshot(browser, document, destination, work):
    """Render a chapter frame in a temporary Chrome profile and cache identical input."""
    digest = hashlib.sha256(document.encode()).hexdigest()
    marker = destination.with_suffix(".sha256")
    if destination.exists() and marker.exists() and marker.read_text() == digest:
        return
    source = destination.with_suffix(".html")
    source.write_text(document)
    with tempfile.TemporaryDirectory(prefix="arena-creation-browser-") as profile:
        command = [
            browser,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--user-data-dir={profile}",
            f"--window-size={WIDTH},{HEIGHT}",
            "--force-device-scale-factor=1",
            "--virtual-time-budget=500",
            f"--screenshot={destination}",
            source.as_uri(),
        ]
        with (work / "browser.log").open("a") as log:
            subprocess.run(command, stdout=log, stderr=log, check=True, timeout=30)
    marker.write_text(digest)


def run_ffmpeg(arguments):
    """Run one bounded media conversion without verbose encoder output."""
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-filter_threads",
            "2",
            "-filter_complex_threads",
            "2",
            "-y",
            *arguments,
        ],
        check=True,
        timeout=600,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=MEDIA / "creation_process.mp4")
    parser.add_argument("--work", type=Path, default=ROOT / "artifacts/workbench_creation_video")
    parser.add_argument("--frames-only", action="store_true")
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    browser = shutil.which("google-chrome") or shutil.which("chromium")
    assert browser is not None, "Chrome or Chromium is required for the chapter graphics"
    assert shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg and ffprobe are required"
    scene = yaml.safe_load((ENVIRONMENT / "scene.yaml").read_text())
    tasks = [yaml.safe_load((ENVIRONMENT / f"task_{number}.yaml").read_text()) for number in (1, 2, 3)]
    assert [len(task["task"]["subtasks"]) for task in tasks] == [4, 7, 2]
    assert sum(relation["kind"] == "clutter_on" for relation in scene["relations"]) == 5
    source_gif = MEDIA / "workbench_cleanup_demo.gif"
    probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(source_gif)]
        )
    )
    demo_duration = float(probe["format"]["duration"])
    frames = []
    for chapter in range(7):
        for reveal in [3] if chapter == 6 else [1, 2, 3]:
            image = work / f"chapter_{chapter + 1:02d}_{reveal}.png"
            screenshot(browser, render_html(chapter, reveal, chapter == 6), image, work)
            frames.append(image)
        print(f"CHAPTER_FRAME {chapter + 1}/7", flush=True)
    if args.frames_only:
        return
    codec = ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-threads", "4"]
    clips = []
    for index, frame in enumerate(frames[:-1]):
        clip = work / f"part_{index:02d}.mp4"
        transition = ["-vf", "fade=t=in:st=0:d=0.18"] if index % 3 == 0 else []
        run_ffmpeg([
            "-loop",
            "1",
            "-framerate",
            str(FPS),
            "-i",
            str(frame),
            "-t",
            str(CHAPTER_SECONDS / 3),
            *transition,
            *codec,
            str(clip),
        ])
        clips.append(clip)
        if index % 3 == 2:
            print(f"CHAPTER_ENCODED {index // 3 + 1}/7", flush=True)
    final_clip = work / "part_18_demo.mp4"
    run_ffmpeg([
        "-loop",
        "1",
        "-framerate",
        str(FPS),
        "-i",
        str(frames[-1]),
        "-ignore_loop",
        "1",
        "-i",
        str(source_gif),
        "-filter_complex",
        f"[1:v]fps={FPS},scale=608:342:flags=lanczos,setsar=1[demo];[0:v][demo]overlay=1261:297:shortest=1[v]",
        "-map",
        "[v]",
        "-t",
        str(demo_duration),
        *codec,
        str(final_clip),
    ])
    print("CHAPTER_ENCODED 7/7", flush=True)
    clips.append(final_clip)
    concat = work / "segments.txt"
    concat.write_text("".join(f"file '{clip.as_posix()}'\n" for clip in clips))
    chapters = work / "chapters.ffmetadata"
    metadata = [";FFMETADATA1", "title=Workbench cleanup - seven-step creation process"]
    timeline = []
    for index, chapter in enumerate(CHAPTERS):
        start = index * CHAPTER_SECONDS
        end = start + (demo_duration if index == 6 else CHAPTER_SECONDS)
        metadata.extend([
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(start * 1000)}",
            f"END={int(end * 1000)}",
            f"title={index + 1}. {chapter['short']}",
        ])
        timeline.append({"step": index + 1, "title": chapter["title"], "start_s": start, "end_s": end})
    chapters.write_text("\n".join(metadata) + "\n")
    run_ffmpeg([
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat),
        "-i",
        str(chapters),
        "-map_metadata",
        "1",
        "-map_chapters",
        "1",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(output),
    ])
    poster = output.with_name("creation_process_poster.png")
    shutil.copy2(work / "chapter_04_3.png", poster)
    preview = output.with_suffix(".gif")
    for gif_width, gif_fps in [(960, 4), (800, 4), (640, 3)]:
        run_ffmpeg([
            "-i",
            str(output),
            "-filter_complex",
            f"fps={gif_fps},scale={gif_width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
            "-loop",
            "0",
            str(preview),
        ])
        if preview.stat().st_size < 10_000_000:
            break
    assert preview.stat().st_size < 10_000_000, "Preview GIF exceeds its 10 MB limit"
    manifest = {
        "video": str(output.relative_to(ROOT)),
        "resolution": [WIDTH, HEIGHT],
        "fps": FPS,
        "duration_s": 6 * CHAPTER_SECONDS + demo_duration,
        "steps": timeline,
        "source_demo_gif": str(source_gif.relative_to(ROOT)),
        "source_demo_sha256": hashlib.sha256(source_gif.read_bytes()).hexdigest(),
        "source_demo_playback_speed": 1.0,
        "source_demo_complete": True,
        "preview": {
            "path": str(preview.relative_to(ROOT)),
            "width": gif_width,
            "fps": gif_fps,
            "bytes": preview.stat().st_size,
        },
        "source_report": str((ENVIRONMENT / "CONSTRUCTION_AND_VALIDATION.md").relative_to(ROOT)),
        "disclosure": (
            "Reconstructed authoring chapters from saved YAML, report, and viewport media; no new simulation run."
        ),
    }
    (work / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
