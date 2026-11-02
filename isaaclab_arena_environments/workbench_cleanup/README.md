# Workbench cleanup in PhysX

[workbench_cleanup.yaml](workbench_cleanup.yaml) defines a workbench with five loose tools,
an oscilloscope on its left, and an open hinged tool case on the cabinet to the left.
The cabinet starts closed. The task is to open its top drawer, deposit the tools one at a
time, and close it. This environment uses `no_embodiment` for force-controlled task
validation; robot reachability, grasping, and learned-policy performance require a chosen
robot and policy.

All seven requested assets come from NVIDIA's
[SimReady dataset](https://huggingface.co/datasets/nvidia/simready-assets/tree/653d91e182011f357cf1644013cc94ddf194d349),
pinned to revision `653d91e182011f357cf1644013cc94ddf194d349`.
There are two instances of `handTool_screwdriver_slotted_55mm_a01` to make five handheld tools.
The additional toolbox is `storage_toolbox_standard_hardCase_d01`.
Packages download to the existing Hugging Face cache; no USDs, textures, or datasets are
stored in this directory.

The source workbench tabletop is 0.668313 m high. A 0.72 cabinet scale brings its top to
0.6690 m. The toolbox uses scale 0.8 and starts with its lid at -1.5707 radians.
Its base is fixed and its links have gravity disabled to keep this decorative lid open.
The oscilloscope and workbench are static scenery. The oscilloscope is anchored at
`[0, -0.5, 0.669313]` because static background assets do not support dynamic pose resets.
Their original meshes and colliders
are retained; the workbench also has a thin reference collider aligned with its existing
tabletop because its source mesh combines the tabletop and backboard. This reference covers
the central 0.49 by 0.65 m work region. The toolbox is anchored above the cabinet so its
normal articulation reset restores the lid and latch angles. Tool placement uses
`ClutterOn` against the measured tabletop reference, with the
default bounding-box checks between foreground assets. Archived [source physics trees](docs/asset_inspection/)
and [surface measurements](docs/inspect_surfaces.log) document the inspected geometry.

The handheld tools use convex-hull approximations of their original collider meshes,
1 mm contact offsets, and linear/angular damping of 2/5. Their original SDF contacts
produced persistent rolling after release. The cabinet retains its original hollow SDF
colliders; no collision geometry is removed, and the task's settling thresholds are retained.

Success uses the existing `OpenDoorTask`, five `ObjectInTask` instances, and `CloseDoorTask`
in a sequential `CompositeTaskBase`. The tool order is slotted, Torx, Phillips, wrench,
then the second slotted screwdriver. Opening requires more than 90% of drawer travel;
closing allows at most 3% (about 10 mm at the configured scale).
Each placement requires all object mesh points inside the moving drawer's local bounds,
support contact with the drawer or another assigned tool, linear speed below 0.02 m/s,
and angular speed below 0.2 rad/s for 15 consecutive control steps. At final success all
five placement conditions and the closed condition must still hold. The earlier open
condition is a milestone, so closing does not invalidate it. Both open and close tasks
reset the cabinet to closed, avoiding conflicting reset events.

The reference examples are
[`workbench_open_drawer_robolab_tools.yaml`](workbench_open_drawer_robolab_tools.yaml)
and the maintained kitchen-bench force-control recipes. No new task, predicate, placement
solver, or asset class is needed.

## Run the demonstration

From the repository root, discover this checkout's running container:

```bash
ARENA_CONTAINER=$(docker ps --filter "volume=$(git rev-parse --show-toplevel)" --format '{{.Names}}' | head -1)
```

Run the reusable force-control runner with the checked-in recipe:

```bash
docker exec --user "$(id -un)" "$ARENA_CONTAINER" isaaclab.sh -p \
  isaaclab_arena/scripts/force_control_runner.py \
  --env_spec isaaclab_arena_environments/workbench_cleanup/workbench_cleanup.yaml \
  --commands isaaclab_arena_environments/workbench_cleanup/workbench_cleanup_force_control.jsonl \
  --output outputs/workbench_cleanup/demo \
  --presets physx --device cpu --visualizer kit
```

The runner applies forces, torques, and drawer joint efforts. It releases each tool before
checking native task progress. It does not teleport objects or write success flags.
It records a video, milestone images, and `validation.json`; assertion failures include
live physics and predicate diagnostics.

## Check success and counterexamples

```bash
docker exec --user "$(id -un)" "$ARENA_CONTAINER" isaaclab.sh -p \
  isaaclab_arena_environments/workbench_cleanup/validate_workbench_cleanup.py \
  --presets physx --output outputs/workbench_cleanup/validation
```

The headless validator reuses the same force recipe and native predicates, then physically
reopens the drawer, removes a previously placed tool, tests an unsupported tool held inside
the drawer, restores it, and resets the environment. It writes `predicate_checks.json`.
Only normal environment reset writes initial state directly.

## Validation results and authoring measurements

Validated in this checkout's discovered Docker container, as the host user, using PhysX.
The headless physical demonstration completed all seven milestones in 60.87 simulated
seconds, within the 130-second task budget. The final top-drawer displacement was
`3.65e-8 m`; all five containment and settled-contact predicates were true. Each tool
had direct drawer support contact, with measured forces from 0.49 to 8.12 N.
The recorded demo also passed, completing in 58.87 simulated seconds after a shorter
initial settling period. Its initial, loaded-drawer, and final scene images were inspected.

| Physical check | Expected native success | Result |
| --- | --- | --- |
| Initially closed, empty drawer | False | Passed |
| All five tools inside, drawer closed | True | Passed |
| Drawer reopened after success | False | Passed |
| Previously placed wrench removed, drawer closed again | False | Passed |
| Wrench held inside without support contact | False | Passed |
| Wrench restored, drawer closed | True | Passed |
| Environment reset | False | Passed |

The validator also checked that the toolbox starts and resets open, milestone history
survives removal of a tool, and reset clears all seven milestones. Seven focused pytest
tests passed in 20.10 s, covering sequential order, current final conditions, isolation
between environment resets, target-local containment, and shared support.
Host pre-commit checks passed for the implementation files.

Recorded artifacts are archived under `docs/`. The commands above generate fresh results
under `outputs/`; archived reports retain the original runtime paths. Video and images
use Git LFS.

- [Physical validation report](docs/validation_hulls/validation.json)
- [Counterexample and reset states](docs/validation_hulls/predicate_checks.json)
- [Focused pytest log](docs/focused_tests.log)
- [Recorded demonstration](docs/demo/demo.mp4)
- [Recorded demonstration report](docs/demo/validation.json)
- [Initial scene](docs/demo/00_start.png), [loaded drawer](docs/demo/05_end.png),
  and [completed scene](docs/demo/06_end.png)
- [All demonstration milestones](docs/demo/)

[authoring_log.jsonl](docs/authoring_log.jsonl) records inference usage and tool-call events
without session text or tool arguments. [authoring_metrics.json](docs/authoring_metrics.json)
contains the corresponding totals and LOC breakdown.

<!-- AUTHORING_METRICS_START -->
Measured from `2026-11-01T15:49:37.971Z` through `2026-11-01T16:24:18.804411+00:00`. These totals cover
this environment-authoring request and exclude the earlier Docker sanity test.
The snapshot excludes subsequent model calls and the final chat response.

| Measurement | Total |
| --- | ---: |
| Wall time | 34 min 41 s |
| Inference calls | 89 |
| Input tokens, including cached context | 14,068,120 |
| Cached input tokens (subset of input) | 13,863,040 |
| Uncached input tokens | 205,080 |
| Output tokens | 56,728 |
| Reasoning output tokens (subset of output) | 20,163 |
| Total input + output tokens | 14,124,848 |
| Production LOC retained | 394 |
| Debug/inspection/accounting LOC retained | 195 |

Token counts are summed from recorded inference usage; cached context is counted again
when reused by another inference. LOC counts nonblank, noncomment source lines, including
YAML and JSONL recipes. Production includes the environment, recipe, and reusable validator.
Debug includes the temporary inspection scripts, recipe, and accounting helper used during
the original run. Their [source snapshots](docs/authoring_sources/) are archived with a `.txt`
suffix. The original paths in the metrics describe that run before archiving. Generated
reports and README prose are excluded.
Per-file LOC and cumulative patch additions, including replaced lines, are in
[authoring_metrics.json](docs/authoring_metrics.json).

| Tool-call level | Type | Calls |
| --- | --- | ---: |
| Orchestration | `exec` | 81 |
| Orchestration | `request_user_input_async` | 1 |
| Orchestration | `sleep` | 6 |
| Nested dispatch | `apply_patch` | 26 |
| Nested dispatch | `clock__curr_time` | 1 |
| Nested dispatch | `exec_command` | 120 |
| Nested dispatch | `view_image` | 5 |
| Nested dispatch | `write_stdin` | 23 |

Orchestration and nested dispatch are separate levels; do not add them as distinct operations.
<!-- AUTHORING_METRICS_END -->
