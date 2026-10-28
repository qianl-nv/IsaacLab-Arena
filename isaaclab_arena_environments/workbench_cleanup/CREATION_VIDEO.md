# Workbench task creation video

[Watch the three-panel video](../../docs/images/workbench_cleanup/creation_process.mp4)
· [GIF preview](../../docs/images/workbench_cleanup/creation_process.gif)
· [Original final demo GIF](../../docs/images/workbench_cleanup/workbench_cleanup_demo.gif)

[![Three-panel video showing agent actions, task graphs, and a saved simulation viewport](../../docs/images/workbench_cleanup/creation_process_poster.png)](../../docs/images/workbench_cleanup/creation_process.mp4)

The video presents seven steps in **3 minutes 24 seconds**, at **1920 × 1080,
20 fps**, with embedded chapter markers. Its three panels show:

- Left: agent actions, concise design rationale, and recorded test findings.
- Middle: progressively revealed graph nodes and edges for asset references,
  spatial relations, physics adapters, sequential task logic, and success checks,
  alongside selected YAML or schematic code excerpts.
- Right: saved simulation viewports, followed by the complete original final demo GIF.

The first six steps reconstruct the authoring process from the
[construction report](CONSTRUCTION_AND_VALIDATION.md), [scene YAML](scene.yaml),
and three task YAMLs. They are an explanatory retrospective, not a recording of
the original editing session. The notes summarize decisions and evidence; the
graph is a selected view of the configuration, not a complete YAML serialization.
Physics and validation-flow diagrams are labeled separately from spatial relations.
No new simulation run was performed to create this video.

| Step | Time | What it shows |
| --- | --- | --- |
| 1. Inspect assets | 0:00–0:12 | SimReady asset selection, joint inspection, and the independent gray-bin substitute. |
| 2. Place the scene | 0:12–0:24 | Shared support references, three `on` edges, and five `clutter_on` edges. |
| 3. Repair physics | 0:24–0:36 | Hollow drawer colliders, retained case inserts, convex tool contacts, and successful fit viewports. |
| 4. Compose tasks | 0:36–0:48 | The three sequential task graphs: 4 socket-set, 7 bin/tool, and 2 device subtasks. |
| 5. Force-test | 0:48–1:00 | Bounded forces, joint efforts, sensor/predicate checks, and boundary captures. |
| 6. Audit success | 1:00–1:12 | Historical completion versus required current conditions; recorded validation outcomes. |
| 7. Final demonstration | 1:12–3:24 | The entire existing 132-second combined GIF, uncut, at its original playback speed. |

The final chapter displays the original validation summary beside the saved demo;
the graph is not live telemetry. Each task starts from its own initial scene.
The original run used command-driven force operation without a robot. Its cable
is visual and the power-button state represents OFF; electrical behavior is not
simulated. Detailed test scope and limitations remain in the construction report.

## Reproduce and verify

Run on the host with Python, PyYAML, Chrome/Chromium, FFmpeg, and ffprobe:

```bash
python3 isaaclab_arena_environments/workbench_cleanup/make_creation_video.py
```

Use `--frames-only` to render the chapter layouts before encoding. The script checks
the current YAML subtask counts and clutter-relation count, renders progressive
graph states, embeds the existing demo GIF, adds chapter metadata, and creates a
GIF preview below 10,000,000 bytes. It leaves the source media unchanged.
Intermediate HTML, PNGs, clips, logs, and the source-GIF hash/timeline manifest go
under `artifacts/workbench_creation_video/`. Published media are under
`docs/images/workbench_cleanup/`.

The delivered video was checked for duration, resolution, chapter count, successful
full decoding, and inclusion of the original GIF in its final panel. Chapter frames
were inspected for text and graph readability. The GIF preview was checked against
the 10 MB limit. No simulator regression testing is claimed for this media-only change.

Asset credits: [NVIDIA](https://huggingface.co/datasets/nvidia/simready-assets),
[ForgeCAD](https://huggingface.co/datasets/ForgeCAD/simready-assets)
(`ratchet_socket_set`, CC BY 4.0; adapted physics), and
[PalatialSim](https://huggingface.co/datasets/PalatialSim/palatial-nv-asset-library)
(`D00814`). Exact source revisions are pinned in `scene.yaml`; see the
[environment README](README.md) for asset and modeling details.
