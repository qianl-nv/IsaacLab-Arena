# DROID workbench validation

DROID is available for all three existing tasks. **Only Task 3 currently has a
successful complete robot rollout. Tasks 1 and 2 remain incomplete.** The
recordings for those tasks are diagnostics, not completion demonstrations.
An IK solution means the requested gripper pose fits the arm's joint limits;
it does not establish a collision-free path, a stable grasp, or task completion.

## Request (spelling normalized)

> Add DROID to the existing workbench cleanup environment. For each of the three
> tasks, validate whether every action is feasible, including gripper reach.
> Produce an IK-based scripted demo showing the robot completing each task.
> Summarize the main steps, time use, and token use.

The requested set of three successful robot demos has **not** been achieved.
The failures below identify what still needs work; they do not prove that the
underlying tasks are impossible for DROID.

## Environment and controller

- [droid.yaml](droid.yaml) uses Arena's `droid_abs_joint_pos`: the Panda arm and
  Robotiq gripper, with continuous finger control (0 open, 1 closed).
- [Task 1](droid_task_1.yaml), [Task 2](droid_task_2.yaml), and
  [Task 3](droid_task_3.yaml) include the original [scene](scene.yaml) and shared
  `task_N_logic.yaml`. The extracted task definitions were compared with the
  original Git versions and are identical. No task thresholds were relaxed.
- The robot base differs per task; it is fixed throughout each episode. This
  is not a demonstration of one base position covering all three tasks.
- [droid_ik.py](droid_ik.py) reads the spawned USD's arm-joint frames and limits
  and solves bounded seven-joint IK using SciPy. Its forward kinematics is
  checked against the live gripper frame. It supplements the existing DROID
  embodiment; it is not a collision-aware planner.
- [droid_demo.py](droid_demo.py) sends robot joint-position and finger actions,
  steps PhysX, and uses Arena's native progress tracker and final success
  predicate. It reuses the existing force demo's camera, cable, display, and
  criterion-reporting helpers only. The robot episodes apply **no external
  object wrench, no object attachment, and no object-pose writes**.
- The demo configures the lid, selected drawer, and power button as passive
  joints. It warms up the articulation constraints, then resets before the
  recorded episode. There are no mid-episode resets. The general YAML runner
  does not apply these demo-specific passive-drive overrides.

| Task | Robot base XYZ (m) | Stand height (m) | Base yaw |
| --- | --- | ---: | ---: |
| 1 | (0.45, 0.00, 0.70) | 0.70 | 180 degrees |
| 2 | (0.50, -0.20, 0.75) | 0.75 | 180 degrees |
| 3 | (0.55, -0.45, 0.70) | 0.70 | 180 degrees |

Task 2 also supplies an initial arm posture near the bin approach to avoid the
stock home posture contacting the rack. The stand footprint is 0.32 by 0.32 m.
The original object placement relations and tool clutter remain in the shared
scene; validation uses placement seed 17.

The asset adapters needed current-API constructor fixes, source case-handle
colliders, small plug/outlet contact margins, convex-hull outlet contacts, and
plug angular damping. Downloads and generated USD wrappers remain in the user
cache. No model files were added to the repository.

## Action-level feasibility

All sampled critical endpoint poses have bounded IK solutions. The JSON audits
record the position/orientation residuals and arm angles for every sample.
These are endpoint checks, not swept-volume or collision certificates.
Physical rollout errors are measured independently; the controller stops when
an endpoint misses by more than 5 cm, when a lift fails, or when the native
subtask check fails.

| Task/action | IK endpoint | Physical evidence | Status |
| --- | --- | --- | --- |
| 1: Close socket case | Reachable | Recorded robot push passes `CloseDoorTask`. | Passed in the Task 1 rollout |
| 1: Open top-left drawer | Reachable | Recorded grasp/pull passes `OpenDoorTask`. | Passed in the Task 1 rollout |
| 1: Put closed case inside drawer | Reachable | The recorded handle-grasp lift misses its target by 0.116 m; containment is false. Other isolated grasps slipped or tipped the case. | Failed attempt |
| 1: Close loaded drawer | Reachable | Not reached in the complete sequence. A separate empty-drawer push also failed to close it. | Not validated |
| 2: Bring overhead bin to table | Reachable | Recorded lift, transfer, and release pass the native bin-on-table milestone. Subsequent motions disturb the bin. | Passed in the Task 2 rollout |
| 2: Pack slotted screwdriver | Pick/place reachable | Recorded grasp passes the physical-lift guard; the drop approach then misses by 0.119 m and containment remains false. | Lift demonstrated; transfer failed |
| 2: Pack Torx screwdriver | Pick/place reachable | An isolated friction grasp lifted the tool to z=0.800 m. No successful containment recorded in that trial. | Lift demonstrated; placement not validated |
| 2: Pack Phillips screwdriver | Pick/place reachable | Exploratory approach/grasp trials did not produce a stable completed transfer. | Not validated |
| 2: Pack combination wrench | Pick/place reachable | Exploratory approach/grasp trials did not produce a stable completed transfer. | Not validated |
| 2: Pack small wrench | Pick/place reachable | Exploratory approach/grasp trials did not produce a stable completed transfer. | Not validated |
| 2: Return loaded bin to rack | Reachable | Full packing has not been completed, so a loaded return was not exercised. | Not validated |
| 3: Switch device off | Reachable | Physical button press passes `PressButtonTask`; rechecked after unplugging. | Passed |
| 3: Unplug and release | Reachable | Initially seated plug is withdrawn, released, and allowed to settle; `UnplugTask` and final task predicate pass. | Passed |

The closed case is approximately 126 mm wide, exceeding the roughly 84 mm open
jaw span. Its approximately 51 mm thickness is graspable in principle, but the
bench surface limits access from below. The front handle's clearance is also
tight relative to the fingers. These explain why a reachable handle pose is
insufficient; they are not an exhaustive grasp-feasibility proof.

The gray bin can be lifted by its rim, but rim grasps tilted it and sometimes
wedged the fingers during release in exploratory trials. Returning a fully
loaded bin remains unvalidated. The 0.83 kg combination wrench and nearby
clutter also require more reliable grasps and paths than the current script.
Other drawer motion was observed during contact; the precise cause of the
failed drawer-closing trial has not been isolated.

### Complete-run recordings

| Task | Native final success | Recording | Machine-readable evidence |
| --- | --- | --- | --- |
| 1 | **false**; 2/4 historical milestones | [Diagnostic GIF](../../docs/images/workbench_cleanup/droid/task_1/diagnostic.gif), [MP4](../../docs/images/workbench_cleanup/droid/task_1/diagnostic.mp4) | [Report](validation/droid_task_1.json), [IK audit](validation/droid_task_1_reachability.json) |
| 2 | **false**; 1/7 historical milestones | [Diagnostic GIF](../../docs/images/workbench_cleanup/droid/task_2/diagnostic.gif), [MP4](../../docs/images/workbench_cleanup/droid/task_2/diagnostic.mp4) | [Report](validation/droid_task_2.json), [IK audit](validation/droid_task_2_reachability.json) |
| 3 | **true**; 2/2 milestones and required final conditions | [Completion GIF](../../docs/images/workbench_cleanup/droid/task_3/demo.gif), [MP4](../../docs/images/workbench_cleanup/droid/task_3/demo.mp4) | [Report](validation/droid_task_3.json), [IK audit](validation/droid_task_3_reachability.json) |

All GIFs are below 10 MB. The MP4s preserve the full rendered rollout, including
failed actions. Media are stored under `docs/images/workbench_cleanup/droid/`;
raw logs, cached experiments, and scratch scripts remain under uncommitted
`artifacts/`.

Task 1's separate IK audit was refreshed to sample the final script's handle
grasp and lift. Its diagnostic report retains the earlier embedded audit,
which also sampled an alternative case-edge grasp; rollout measurements were
not replaced by the later audit.

### Subtask boundary snapshots

| Recording/action | Start | End |
| --- | --- | --- |
| Task 1: case closure | [Start](../../docs/images/workbench_cleanup/droid/task_1/00_start.png) | [End](../../docs/images/workbench_cleanup/droid/task_1/00_end.png) |
| Task 1: drawer opening | [Start](../../docs/images/workbench_cleanup/droid/task_1/01_start.png) | [End](../../docs/images/workbench_cleanup/droid/task_1/01_end.png) |
| Task 1: failed case transfer | [Start](../../docs/images/workbench_cleanup/droid/task_1/02_start.png) | [Failure](../../docs/images/workbench_cleanup/droid/task_1/02_end.png) |
| Task 2: bin transfer | [Start](../../docs/images/workbench_cleanup/droid/task_2/00_start.png) | [End](../../docs/images/workbench_cleanup/droid/task_2/00_end.png) |
| Task 2: failed slotted-tool transfer | [Start](../../docs/images/workbench_cleanup/droid/task_2/01_start.png) | [Failure](../../docs/images/workbench_cleanup/droid/task_2/01_end.png) |
| Task 3: button press | [Start](../../docs/images/workbench_cleanup/droid/task_3/00_start.png) | [End](../../docs/images/workbench_cleanup/droid/task_3/00_end.png) |
| Task 3: unplugging | [Start](../../docs/images/workbench_cleanup/droid/task_3/01_start.png) | [End](../../docs/images/workbench_cleanup/droid/task_3/01_end.png) |
| Task 3: final button recheck | [Start](../../docs/images/workbench_cleanup/droid/task_3/00_recheck_start.png) | [End](../../docs/images/workbench_cleanup/droid/task_3/00_recheck_end.png) |

Unexecuted subtasks have no start/end screenshots. The
[slotted-tool lift](../../docs/images/workbench_cleanup/droid/feasibility/slotted_screwdriver_lift.png),
[Torx-tool lift](../../docs/images/workbench_cleanup/droid/feasibility/torx_screwdriver_lift.png),
and [failed isolated drawer closure](../../docs/images/workbench_cleanup/droid/feasibility/drawer_closed_independent.png)
are **exploratory snapshots**, not a successful task sequence. Their
[measured state](validation/droid_exploratory_actions.json) is retained separately;
some exploratory tests initialized individual object/robot poses before the
isolated action.

## Reproduce

Use the clone's ready Docker runtime as the host user. Resolve the container
instead of hardcoding its name:

```bash
ARENA_CONTAINER=$(docker ps --filter "volume=$(git rev-parse --show-toplevel)" --format '{{.Names}}' | head -1)
docker exec "$ARENA_CONTAINER" su "$(id -un)" -c '
  cd /workspaces/isaaclab_arena &&
  DISPLAY=:1 HF_HUB_CACHE="$HOME/.cache/arena-workbench-hf" \
  ./submodules/IsaacLab/isaaclab.sh -p \
    isaaclab_arena_environments/workbench_cleanup/droid_demo.py \
    --task 3 --output artifacts/workbench_cleanup_droid/reproduction --visualizer kit
'
```

Use the display configured for your container if it differs from `:1`. Change
`--task` to 1 or 2 to reproduce the diagnostic candidate plans. These deliberately
exit with a failure when the robot or task check fails. Add `--no-record` to skip
media, or `--audit-only --visualizer none` to perform endpoint IK checks without
executing task actions. Audit-only reports use `success: null`, never `true`.

Each `task_N/` output contains `report.json`, `reachability.json`,
`progress.json`, `demo.mp4`, and start/end PNGs for every attempted subtask.
Media/progress files are absent in audit-only mode. Recorder files are isolated
by task directory to prevent parallel tasks from locking the same HDF5 file.
Use different output directories for concurrent runs of the same task.

## Validation scope and remaining work

Validation used Isaac Sim/Isaac Lab in the existing container, CPU PhysX,
one environment, seed 17, 120 Hz physics, and 20 fps video. The default DROID
self-collision setting is disabled. Cartesian interpolation and joint
interpolation do not supply collision avoidance; an endpoint tracking check
also does not certify every intermediate contact as safe for hardware.

Task 3 uses the existing simplified plug: gravity is disabled, linear and
angular damping are 4, and its cable is visual. The button's pressed position
represents off; there is no electrical simulation. Unplugging can disturb the
free-standing scope and release its passive button, so the controller rechecks
the current condition and physically presses it again if needed. It waits for
both required final conditions; historical milestones alone do not count.
The final Task 3 recording repeated the earlier successful rollout and also
passed with endpoint tracking guards enabled. This is evidence for this seed
and setup, not a success-rate study across randomized scenes.

The next concrete work is a collision-aware grasp/path search for the case and
five tools, a bin release that leaves a useful packing pose, diagnosis of the
drawer contact interference, and complete loaded-drawer/bin rollouts. A rigid
grasp constraint was considered but was not used to turn failed physical
grasps into successful recordings.

Checks completed: all three DROID configurations built and reset in the runtime;
all 24 sampled endpoint IK checks passed; Task 3 passed twice; Task 1 and Task 2
produced explicit failed reports. Host pre-commit checks passed for the changed
Python, YAML, and documentation. Markdown links, report JSON, GIF sizes, task
definition equivalence, and `git diff --check` were checked. The full pytest
suite and the original force-demo sequences were not rerun.

## Process, time, and token usage

Work started **2026-10-28 13:24:03 UTC**. The final validation checkpoint was
**16:34:46 UTC**, giving **3 h 10 min 43 s** elapsed through validation (about
3 h 11 min including this report). Approval-wait time was **0 seconds**.

1. Read the environment-authoring and container workflows; inspect the scene,
   task predicates, DROID actions, asset colliders, and joint frames.
2. Split shared task logic from the embodiment; add three DROID entry points,
   continuous gripper control, and per-task base placement.
3. Build bounded IK and validate its forward kinematics against the simulator;
   audit critical poses and test physical contact approaches.
4. Iterate case, drawer, bin, tool, button, and plug actions. This contact/grasp
   work dominated elapsed time; several numerical IK solutions failed in
   physics. Preserve failures instead of weakening the success checks.
5. Record complete attempts, verify native final state, publish media and JSON
   evidence, and run source/configuration checks.

The longest observed trial windows were case/drawer work (about 14:00–16:17),
bin/tool work (about 14:09–16:17), button/plug refinement and recording
(about 13:37–15:30), final recorded reruns, and documentation/media checks.
Trials were interleaved and sometimes concurrent, so these windows **must not
be added as independent step durations**. No per-category active-time profiler
was available. Individual run wall times are measured in each JSON report.

| Published rollout | Simulation time | Wall time, including simulator startup |
| --- | ---: | ---: |
| Task 1 diagnostic | 65.25 s | 147.87 s |
| Task 2 diagnostic | 81.25 s | 334.70 s |
| Task 3 success | 57.50 s | 360.83 s |

These are individual run timings, not total task-development time. Concurrent
runs and rendering load affect the wall times.

**Token usage: unavailable.** This session exposes neither a cumulative input/
output token counter nor a budget report with usage. No estimate is presented
as a measured count.

Skills used: [author-environment](../../skills/developer/author-environment/SKILL.md)
and [dev-container](../../skills/developer/dev-container/SKILL.md). Reused APIs
include `ArenaEnvGraphSpec`, `ArenaEnvBuilder`, DROID absolute-joint actions,
`arena_world`, `progress_tracker`, and `task_success_from_progress`.

The largest tooling opportunities are a collision-aware IK/grasp audit with
contact explanations, automatic base/posture search across all subtask poses,
and an action probe that records robot tracking, finger contacts, object slip,
and current predicates together. These would reduce the manual grasp and
collision diagnosis that dominated this attempt.
