# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Copy viewport evidence and caption the recorded demo using its actual progress events."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "artifacts/jetson_thor_packing/demo/task_1"
DESTINATION = ROOT / "docs/images/jetson_thor_packing"


def ass_time(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, remainder = divmod(remainder, 60)
    return f"{int(hours)}:{int(minutes):02d}:{remainder:05.2f}"


def main():
    report = json.loads((SOURCE / "validation.json").read_text())
    assert report["success"] and all(report["arena_success_termination"]), "Only publish a successful demonstration"
    assert not report["active_external_force_holds"]
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for path in SOURCE.glob("*.png"):
        shutil.copy2(path, DESTINATION / path.name)
    shutil.copy2(SOURCE.parents[1] / "assets/blender_scene.png", DESTINATION / "blender_scene.png")
    duration = report["video_frames"] / 20
    captions = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1280",
        "PlayResY: 720",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            "Style: Default,DejaVu"
            " Sans,22,&H00FFFFFF,&H00FFFFFF,&H00182028,&H90182028,0,0,0,0,100,100,0,0,3,9,0,2,20,20,18,1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def caption(start, end, text):
        captions.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{text}")

    caption(0, 2.0, "JETSON AGX THOR | Physics-force packing demonstration | No robot")
    starts = []
    packed_time = None
    for i, event in enumerate(report["events"]):
        if event["boundary"] == "start":
            # The harness captures at 20 fps and adds one extra frame at every boundary.
            starts.append((event["simulation_time_s"] + i / 20, event))
        if event["boundary"] == "end" and event["subtask"] == 5:
            packed_time = event["simulation_time_s"] + i / 20
    assert packed_time is not None
    for i, (start, event) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else packed_time
        caption(start, end, f"{event['subtask'] + 1}/6 | {event['title']}")
    caption(packed_time, duration - 0.05, "6/6 placed | External forces released | Checking settled final conditions")
    caption(duration - 0.05, duration + 4, "ARENA SUCCESS: TRUE | All 6 subtasks complete and currently satisfied")
    subtitle = SOURCE / "captions.ass"
    subtitle.write_text("\n".join(captions) + "\n")
    video = DESTINATION / "packing_demo.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(SOURCE / "demo.mp4"),
            "-vf",
            f"tpad=stop_mode=clone:stop_duration=4,subtitles={subtitle}",
            "-c:v",
            "libx264",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(video),
        ],
        check=True,
    )
    gif = DESTINATION / "packing_demo.gif"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-filter_complex",
            (
                "fps=8,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];"
                "[b][p]paletteuse=dither=bayer:bayer_scale=4"
            ),
            "-loop",
            "0",
            str(gif),
        ],
        check=True,
    )
    assert gif.stat().st_size < 10_000_000, "Reduce GIF resolution or frame rate to stay below 10 MB"
    print(
        json.dumps(
            {
                "video": str(video),
                "gif": str(gif),
                "gif_bytes": gif.stat().st_size,
                "duration_seconds": duration + 4,
                "viewport_images": len(list(DESTINATION.glob("*.png"))),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
