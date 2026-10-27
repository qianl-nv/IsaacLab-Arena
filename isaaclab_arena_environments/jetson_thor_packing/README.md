# Jetson AGX Thor kit packing

An Arena task packs four accessories into the bottom layer of a cardboard carton,
installs the removable board housing, then places the Jetson AGX Thor Developer Kit.
The parts start scattered on a table. The demonstration uses physical forces and
torques with `NoEmbodiment`.

[Watch the demonstration](../../docs/images/jetson_thor_packing/packing_demo.mp4)
· [GIF preview](../../docs/images/jetson_thor_packing/packing_demo.gif)
· [Final viewport](../../docs/images/jetson_thor_packing/06_end.png)
· [Blender construction preview](../../docs/images/jetson_thor_packing/blender_scene.png)

## Request and references

The [original user prompt](../../artifacts/jetson_thor_packing/prompt.txt) requests
photo-based Blender MCP assets, fitted multilayer packaging, an ordered Arena packing
task, and a successful physics-force demonstration with video. The four references
are `~/Downloads/jetson/Screenshot from 2026-10-26 11-{42-26,43-09,43-43,44-02}.png`.

NVIDIA's [quick-start guide](https://docs.nvidia.com/jetson/agx-thor-devkit/user-guide/latest/quick_start.html)
confirms the upper kit slot and lower AC cable(s), USB-A/USB-C cable, and USB-C power
supply. The photos show two AC leads, so this scene includes US and EU plug variants.
The [NVIDIA product introduction](https://developer.nvidia.com/blog/introducing-nvidia-jetson-thor-the-ultimate-platform-for-physical-ai/)
specifies a 243.19 × 112.40 × 56.88 mm developer kit, including feet and thermal solution,
with a T5000 module, 128 GB memory, and 1 TB NVMe storage. The board asset represents
the complete enclosed kit shown in the photos.

## Construction and fit

`build_with_mcp.py` connects through the MCP Python client to the installed
`mcp-for-blender` stdio server and calls `execute_blender_code`. Blender runs
`build_assets.py`, creates a dedicated scene, exports seven USD assets, saves a
`.blend`, and renders a preview. The existing service on port 9876 did not respond;
a separate Blender instance on 9877 was used without changing that instance.

The silver enclosure includes its cooling grille, feet, representative I/O ports,
and printed labels. Cables have coiled geometry, ties, and plugs. The power adapter
and captive USB-C lead form one rigid assembly. The carton has an open fixed lid,
separate lower compartments, tray support ledges, and a removable lined upper tray.

| Dimension | Value | Basis |
| --- | --- | --- |
| Developer kit | 243.19 × 112.40 × 56.88 mm nominal | NVIDIA dimensions |
| Exported kit bounds | 243.19 × 112.40 × 56.85 mm | USD geometry measurement |
| Carton exterior | 360 × 220 × 160 mm | Photo-based estimate |
| Upper tray exterior | 342 × 202 × 66 mm | Designed to fit carton |
| Board well | 257 × 126 mm | 6.90 / 6.80 mm clearance per side |
| Tray clearance | 4 mm per side | Carton interior versus tray exterior |
| Tray underside above carton bottom | 80 mm | Support ledges and dividers |
| Clearance above the packed adapter | Approximately 25.7 mm | Adapter top versus tray underside |

Packaging, accessory dimensions, masses, and friction are modeling assumptions.
These assets are a photo-based reconstruction with verified simulated fit; they
are not manufacturer packaging CAD. Cardboard and coils are rigid.

`assets.py` attaches USD rigid-body physics to the Blender exports. Each hollow
housing uses separate convex collision panels. Decorative meshes have no collision.
The carton and lower receptacles are kinematic; the six movable assemblies are dynamic.
There are 64 collision panels across the background and parts. Contact offsets are
0.5 mm, with zero restitution.

## Scene and task

- [scene.yaml](scene.yaml): shared table, carton, compartment references, six parts,
  fixed initial placement relations, and camera configuration.
- [task.yaml](task.yaml): six sequential subtasks, with every final subtask state
  required to remain true.
- [tasks.py](tasks.py): `EnterHousingTask`, a small `ObjectInTask` extension used for
  the tray and board. It first observes the object outside its housing after its
  subtask becomes active, then uses the existing containment, contact, and settling
  checks. This prevents crediting a board already packed before the tray is installed.
- [force_demo.py](force_demo.py): reuses the workbench demonstration's force controller,
  stepping, viewport capture, and boundary logging; supplies this packing sequence.

| Step | Atomic task | Start | End |
| --- | --- | --- | --- |
| US AC lead into left compartment | `ObjectInTask` | [Image](../../docs/images/jetson_thor_packing/00_start.png) | [Image](../../docs/images/jetson_thor_packing/00_end.png) |
| EU AC lead beside it | `ObjectInTask` | [Image](../../docs/images/jetson_thor_packing/01_start.png) | [Image](../../docs/images/jetson_thor_packing/01_end.png) |
| USB cable into middle compartment | `ObjectInTask` | [Image](../../docs/images/jetson_thor_packing/02_start.png) | [Image](../../docs/images/jetson_thor_packing/02_end.png) |
| Power adapter and captive lead into right/middle housing | `ObjectInTask` | [Image](../../docs/images/jetson_thor_packing/03_start.png) | [Image](../../docs/images/jetson_thor_packing/03_end.png) |
| Upper tray onto support ledges | `EnterHousingTask` | [Image](../../docs/images/jetson_thor_packing/04_start.png) | [Image](../../docs/images/jetson_thor_packing/04_end.png) |
| Kit into upper tray | `EnterHousingTask` | [Image](../../docs/images/jetson_thor_packing/05_start.png) | [Image](../../docs/images/jetson_thor_packing/05_end.png) |

Every placement requires full bounding-box containment, contact with its intended
receptacle, linear speed below 0.015 m/s, angular speed below 0.1 rad/s, and 20 consecutive
control steps of settling. The final condition requires recorded sequential completion
and all six current settled placements. The initial outside predicates are historical
requirements and are expected to be false at completion.

## Validation and artifacts

- [Geometry report](../../artifacts/jetson_thor_packing/geometry_validation.json):
  independently exported collision panels have no interpenetration at designed resting
  poses, using a 10 micrometre tolerance. It also measures board dimensions and clearances.
- [Behavioral validation](../../artifacts/jetson_thor_packing/validation/task_1/validation.json):
  the full force-driven sequence plus wrong-compartment, ordering, removal/replacement,
  and reset checks.
- [Recorded-run report](../../artifacts/jetson_thor_packing/demo/task_1/validation.json):
  native Arena termination, subtask completion, current predicates, final poses,
  velocities, and boundary events.
- [Blender project](../../artifacts/jetson_thor_packing/assets/jetson_thor_packing.blend),
  [USD assets](../../artifacts/jetson_thor_packing/assets/), and
  [MCP execution result](../../artifacts/jetson_thor_packing/assets/mcp_result.json).

The validation uses CPU PhysX with Isaac Sim 6.2 / Isaac Lab 3.0, one environment,
seed 17, 120 Hz physics, and 60 Hz task updates. Gravity remains enabled. Motions use
bounded PD wrenches with gravity compensation; every object is released before its
settled placement is accepted. No object poses are directly written during packing.
Reset uses Arena's ordinary reset path. This establishes force-based solvability;
robot grasping and reachability are outside this demonstration.

Media are copied into `docs/images/jetson_thor_packing/`. The MP4 is 1280 × 720 at
20 fps; its last frame is held for four seconds to make the success caption readable.
The GIF is 640 × 360 at 8 fps and is below 10 MB. Captions come from the recorded
progress events and successful native termination report.

## Reproduce

Start Blender with its MCP addon enabled. The host-side generation command uses the
existing MCP service; choose its port explicitly. It creates its own Blender scene.

```bash
uv run --no-project --with mcp-for-blender python \
  isaaclab_arena_environments/jetson_thor_packing/build_with_mcp.py \
  --port 9877 --prompt-file artifacts/jetson_thor_packing/prompt.txt
```

Discover this checkout's running container and run Arena as the host user:

```bash
ARENA_CONTAINER=$(docker ps --filter "volume=$(git rev-parse --show-toplevel)" --format '{{.Names}}' | head -1)
docker exec "$ARENA_CONTAINER" su $(id -un) -c \
  'cd /workspaces/isaaclab_arena && DISPLAY=:1 ./submodules/IsaacLab/isaaclab.sh -p isaaclab_arena_environments/jetson_thor_packing/force_demo.py --no-record --negative-checks --output artifacts/jetson_thor_packing/validation'
docker exec "$ARENA_CONTAINER" su $(id -un) -c \
  'cd /workspaces/isaaclab_arena && DISPLAY=:1 ./submodules/IsaacLab/isaaclab.sh -p isaaclab_arena_environments/jetson_thor_packing/force_demo.py'
docker exec "$ARENA_CONTAINER" su $(id -un) -c \
  'cd /workspaces/isaaclab_arena && ./submodules/IsaacLab/isaaclab.sh -p isaaclab_arena_environments/jetson_thor_packing/validate_geometry.py'
python3 isaaclab_arena_environments/jetson_thor_packing/publish_demo.py
```

`--inspect` captures the initial scene without packing. `--no-record` skips viewport
capture. Generated models and runtime artifacts remain outside the source package.

## Process notes

Skills used: [author-environment](../../skills/developer/author-environment/SKILL.md)
and [dev-container](../../skills/developer/dev-container/SKILL.md).
Arena APIs used: `ArenaEnvGraphSpec`, `ArenaEnvBuilder`, `ObjectReference`,
`ObjectInTask`, `CompositeTaskBase`, `TrueForConsecutiveStepsCfg`, `ProgressTracker`,
`ArenaWorld`, and the native termination manager. Blender MCP supplied
`get_scene_info` and `execute_blender_code`; USD export and rendering ran inside Blender.

Both the behavioral validation and the final recorded run report `success: true`,
`arena_success_termination: [true]`, six completed subtasks, and no active external
force holds. All seven behavioral checks passed: initial state rejection, wrong
compartment rejection, rejection of a board packed before subtask activation,
success revocation after removal, acceptance of a new entry, success restoration
after replacement, and reset clearing success. Source pre-commit checks and local
documentation links also passed.

The five most time-consuming phases, approximately ranked from the session, were:

| Rank | Phase | Addition that could shorten it |
| --- | --- | --- |
| 1 | USD physics integration, scene building, and force/contact validation | An Arena asset preflight that checks exported collider ancestry, hollow collision geometry, physical units, and supported anchor rotations before starting Kit |
| 2 | Blender geometry construction and export iteration | A Blender-to-Arena skill with version-aware USD export options and reusable carton, insert, connector, and cable primitives |
| 3 | Video recording, camera framing, and evidence publication | A reusable Arena force-demo CLI with automatic camera fitting, subtask screenshots, progress captions, and bounded GIF export |
| 4 | Reference research and finding a responsive Blender MCP endpoint | An asset-authoring preflight that inventories local references and checks MCP connectivity and addon capabilities |
| 5 | Placement-order edge cases, regression checks, and documentation | A stock new-entry option for containment tasks, plus a validation/report command covering already-packed, wrong-target, removal, and reset cases |

These are proposed additions, not commands currently supplied by Arena.

Execution time through final artifact validation: **35 min 10 sec**
(2026-10-26T18:50:06.715Z to 2026-10-26T19:25:16.963906+00:00); approval wait: **0 seconds**.
At that checkpoint, the session counter reports **7,132,754 total tokens**:
7,070,225 input, including 6,951,040 cached input,
and 62,529 output. These API totals count reused context on each call;
cached input is a subset of input. They exclude subsequent bookkeeping and this turn's
final answer. See [execution accounting](../../artifacts/jetson_thor_packing/execution_accounting.json).
