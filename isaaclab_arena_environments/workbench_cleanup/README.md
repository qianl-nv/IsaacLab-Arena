# Workbench cleanup in PhysX

Open the cabinet's top drawer, put five tools into it one by one, and close it.
The workbench has a central tool pile and an oscilloscope on the operator's left.
An open toolbox sits on the cabinet farther to the left. World +X faces the
operator and -Y points left. Assets retain their original scale, meshes, and enabled colliders. The five
small tools use convex-hull collision approximation; the source SDF colliders
produced persistent rolling that failed the native settling condition. Spawned
tool instances are made editable so these overrides actually apply. Contact/rest
offsets are 0.001/0 m; linear/angular damping is 0.1/5.0 s⁻¹. The validator checks
the live USD properties before manipulating the tools. The workbench and oscilloscope
are static scene fixtures.

The five tools are a slotted 5.5 mm screwdriver, a Torx T10 screwdriver, a
Phillips PH2 screwdriver, and two copies of the combination wrench. The second
wrench supplies the fifth tool from the four requested tool asset types.

![Initial workbench cleanup scene](docs/demo/00_start.png)

## Files

- `workbench_cleanup_physx.yaml`: scene, relation placement, and native task semantics.
- `workbench_cleanup_force_control.jsonl`: physical drawer-effort and rigid-body wrench recipe.
- `validate_cleanup.py`: runs that recipe and verifies false-success cases and reset isolation.
- `workbench_cleanup_experiment.yaml`: one passive episode through timeout, with an evaluation report.
- `workbench_cleanup_smoke.yaml`: includes the full environment with a 10-second smoke timeout.
- [docs/](docs/): archived media, validation results, evaluation reports, and run logs.
- [docs/work_log.json](docs/work_log.json): task-scoped timing, tokens, inference calls, tool calls, and LOC accounting.

The environment uses `no_embodiment` for a policy-independent force demonstration.
This verifies scene physics and task predicates; it does not establish robot
reachability, grasp feasibility, or learned-policy performance. A robot/policy
integration can reuse the same scene and tasks after checking reachability.

## Run

From the repository root, discover the container mounting this checkout:

```bash
ARENA_CONTAINER=$(docker ps --filter "volume=$(git rev-parse --show-toplevel)" --format '{{.Names}}' | head -1)
```

Run the complete validation with video and milestone images:

```bash
docker exec --user "$(id -un)" "$ARENA_CONTAINER" \
  isaaclab.sh -p isaaclab_arena_environments/workbench_cleanup/validate_cleanup.py \
  --env_spec isaaclab_arena_environments/workbench_cleanup/workbench_cleanup_physx.yaml \
  --commands isaaclab_arena_environments/workbench_cleanup/workbench_cleanup_force_control.jsonl \
  --output artifacts/workbench_cleanup/validated --presets physx --visualizer kit
```

Add `--no_record --visualizer none` to run headlessly without media capture.
To run only the positive demonstration,
replace `validate_cleanup.py` with `isaaclab_arena/scripts/force_control_runner.py`.
Both commands require exactly one environment. The recipe applies joint efforts
and external forces/torques; it never writes object poses or joint positions to
complete a task. Pose and joint writes occur only during normal scene reset.

Run the passive evaluation smoke test (zero-action policy, no model server):

```bash
docker exec --user "$(id -un)" "$ARENA_CONTAINER" \
  isaaclab.sh -p isaaclab_arena/evaluation/experiment_runner.py \
  --experiment_config isaaclab_arena_environments/workbench_cleanup/workbench_cleanup_experiment.yaml \
  --viz none
```

## Success definition

The seven sequential subtasks reuse `OpenDoorTask`, five `ObjectInTask` instances,
and `CloseDoorTask`. The placement order is slotted, Torx, Phillips, wrench 1,
wrench 2. Both drawer tasks reset to closed, avoiding conflicting reset events.

- The top drawer must first open beyond 85% of its 0.46218 m travel.
- Every tool must have all sampled collision-mesh points inside the moving
  drawer's local bounds, have filtered contact of at least 0.01 N with the drawer
  or another deposited tool, and settle for 15 consecutive control steps.
- Settled speed thresholds are 0.03 m/s linear and 0.15 rad/s angular.
- Final closure requires at most 3% travel (about 13.9 mm).
- Every placement condition and drawer closure must hold at final success.
  Earlier opening is a recorded milestone and need not remain true.

The YAML root exposes Arena's existing `desired_subtask_success_state` option.
That small schema/conversion extension prevents latched placement history from
accepting a tool that was subsequently removed. No new task or progress tracker
is introduced. Containment follows the existing drawer-local bounding-volume
predicate, with physical contacts and the original concave drawer collider.

The workbench's actual top is 0.6683 m high; its backboard reaches 1.3841 m.
Two invisible, aligned reference boxes identify the worktop and its central tool
region for relation placement. They supplement the original colliders. Tool
release poses use `clutter_on` with random yaw and seed 7, followed by physical
settling. The oscilloscope and open toolbox are fixed fixtures anchored at their measured
support heights. Anchoring the toolbox also retains its joint reset event, so
the lid starts open after every reset.

## Validation results

The headless PhysX force validation passed on 2026-10-31 in the checkout's
`isaaclab_arena-latest-control` container, running as the host user. All seven
subtasks completed in **65.8 simulated seconds**. The final top-drawer position
was **4.79e-8 m**, and all five current containment/support/settling predicates
were true. All **13 semantic checkpoints** passed.

| Physical case | Native success |
| --- | --- |
| Empty closed drawer; partial cleanup; all tools loaded but drawer open | False |
| All five tools settled inside the closed drawer | True |
| Reopen after success | False |
| Remove a previously completed tool, then close | False |
| Hold a tool fully inside the drawer without support contact | False |
| Return the tool, release it, and close | True |
| Reset after a completed episode | False; all seven progress flags cleared |

The hovering case additionally asserts full mesh-point containment, zero qualifying
support contact, and a false placement predicate. Initial and reset checks verify
five tools on the bench, left-side fixture positions, the open toolbox, and live
tool collision/damping overrides.

Reports: [positive state](docs/validated/validation.json),
[semantic checkpoints](docs/validated/semantic_checks.json),
and [milestone times](docs/validated/progress.json).
The diagnostic launcher adds failure logging around the shared runner; it does
not change task predicates or controller behavior.

Focused regression checks: **58 pytest tests passed** (42 graph-schema tests,
plus graph conversion and 15 task-progress tests). These cover the YAML option,
current final conditions, temporal tracking, and selective reset behavior.
Host pre-commit checks also passed for the implementation. Archived console logs:
[schema tests](docs/debug/schema_tests.log.gz),
[conversion and progress tests](docs/debug/progress_tests.log.gz),
[force validation](docs/debug/validation.log.gz),
[recorded demo](docs/debug/demo.log.gz), and
[evaluation smoke](docs/debug/experiment_smoke.log.gz).
The [artifact manifest](docs/artifact_manifest.json) records original paths and
SHA-256 hashes, including final-newline normalization required by formatting hooks.
Compressed log hashes refer to the decompressed contents.

The separately recorded positive demonstration also passed all seven subtasks
in 65.8 simulated seconds: [video](docs/demo/demo.mp4),
[initial scene](docs/demo/00_start.png),
[five tools in the open drawer](docs/demo/05_end.png),
[closed drawer](docs/demo/06_end.png), and
[native success report](docs/demo/validation.json).

The Experiment Definition also completed successfully: one environment, one rebuild,
one 10-second episode, zero-action policy, PhysX, and headless visualization.
The canonical run status is `completed`; task success is **0%**, as expected for
a passive policy. See the [HTML evaluation report](docs/evaluations/2026-10-31_18-44-34/index.html)
and [canonical result](docs/evaluations/2026-10-31_18-44-34/arena_experiment_result.json).
The smoke wrapper includes the full environment and changes only its episode
timeout; the full task's timeout remains 285 seconds. No model server or CLI
overrides were used. The earlier 120-step smoke produced no episode, and the
full-timeout passive run was interrupted to shorten the smoke check. Their [run logs](docs/debug/) are preserved as gzip files. Earlier report and episode
records are archived under [the 120-step run](docs/evaluations/2026-10-31_18-36-00/)
and [the interrupted run](docs/evaluations/2026-10-31_18-40-09/).
Generated HDF5 datasets remain in the original local output directories.

## Asset provenance and reuse

All eight asset identities come from [NVIDIA SimReady Assets on Hugging Face](https://huggingface.co/datasets/nvidia/simready-assets),
licensed CC-BY-4.0, revision `653d91e182011f357cf1644013cc94ddf194d349`:

- `furniture_workbench_standard_e01`
- `fixture_cabinet_b01`
- `testingTool_oscilloscope_a01`
- `handTool_screwdriver_slotted_55mm_a01`
- `handTool_screwdriver_torx_t10_a01`
- `handTool_screwdriver_phillips_ph2_a01`
- `handTool_wrench_combination_a01`
- `storage_toolbox_carry_hardCase_c01` (additional open-toolbox prop)

Downloads stay in the runtime's Hugging Face cache. Asset binaries are not added
to the repository. Cached USD wrappers fix the cabinet/toolbox bases, expose the
toolbox articulation root, and make non-interactive fixtures static. Source USDs
remain unchanged.

Reference examples: `workbench_open_drawer_robolab_tools.yaml` for moving-drawer
containment, the kitchen-bench bananas-in-bowl force recipe, and the documented
composite-task final-state option. The generic `PhysicalCommandRunner` supplies
all force controllers, stepping, recording, and native progress inspection.

## Work accounting

Measured from `2026-10-31T18:04:43.182Z` through `2026-10-31T18:45:53.178762+00:00`.
This covers the workbench task only; the earlier Docker sanity-test request is excluded.
Counts include completed model responses available at the cutoff; final report-writing
and chat overhead after that cutoff are excluded.

| Metric | Measured value |
| --- | ---: |
| Wall time | 41 min 10.0 s (2,469.997 s) |
| LLM inference calls | 138 |
| Input tokens, including repeated context | 19,587,102 |
| Cached input tokens (included above) | 19,352,704 |
| Uncached input tokens | 234,398 |
| Output tokens | 74,708 |
| Reasoning output tokens (included above) | 32,648 |
| Total input + output tokens | 19,661,810 |
| Learned-policy inference calls | 0 |

### Substep breakdown

This is a **retrospective allocation**, not separately instrumented stage timing.
Generation includes subsequent fixes; test time includes retries, physical validation,
recording, and evaluation smoke runs. Mixed tool batches are assigned to their dominant
action. Background tests overlapped other work, so these are non-overlapping allocations
of the original wall time, not individual process runtimes.

| Substep | Allocated wall time | LLM calls | Input tokens | Output tokens | Total tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Generate/fix environment YAML | 13m 48.4s | 59 | 8,418,065 | 26,687 | 8,444,752 |
| Generate force demo and validator | 1m 57.8s | 4 | 632,402 | 4,899 | 637,301 |
| Generate/fix experiment config | 2m 56.4s | 18 | 1,385,553 | 6,177 | 1,391,730 |
| Run/pass tests and physical validation | 14m 57.9s | 46 | 7,341,368 | 20,528 | 7,361,896 |
| README, accounting, and context overhead | 7m 29.5s | 11 | 1,809,714 | 16,417 | 1,826,131 |
| **Total** | **41m 10.0s** | **138** | **19,587,102** | **74,708** | **19,661,810** |

Every recorded inference and elapsed interval is assigned once; totals reconcile exactly
with the frozen original accounting snapshot (displayed durations are rounded). Token
totals include cached input and repeated context; they are not counts of unique text.
The exact per-substep cached/reasoning counts, reviewed tool-index assignments, and
individual intervals are in [work_breakdown.json](docs/work_breakdown.json).
Regenerate it from the frozen `docs/work_log.json` with
`python isaaclab_arena_environments/workbench_cleanup/docs/break_down_usage.py` from the repository root.
The cost of this follow-up analysis and later artifact relocation is excluded from
the original task totals. Paths inside the frozen accounting records describe the
original workspace layout; the artifact manifest maps archived output locations.

Tool calls by type (orchestration wrappers are listed separately):

| Tool | Calls |
| --- | ---: |
| `apply_patch` | 8 |
| `clock__curr_time` | 2 |
| `exec_command` | 171 |
| `view_image` | 6 |
| `web__run` | 1 |
| `write_stdin` | 28 |
| `exec` orchestration wrapper | 131 |
| `sleep` | 6 |

| Added physical LOC | Lines |
| --- | ---: |
| Production runtime/configuration | 236 |
| Retained force demo and validation | 222 |
| Regression tests | 13 |
| Total delivered code/configuration/tests | 471 |
| API documentation | 5 |
| Temporary diagnostic/debug scripts and recipes | 204 |

`docs/work_log.json` contains individual inference and tool-call records without
conversation content. Cached input tokens are a subset of input tokens; reasoning
tokens are a subset of output tokens. Policy inference calls are zero because
this demonstration uses physical controllers.

LOC counts physical added lines, including comments and blanks. Production scene
and API code, retained validation code, regression tests, and temporary debug
scripts are reported separately. Generated logs/media, this README, and telemetry
JSON are excluded. Debug LOC is retained diagnostic code, not cumulative editing
churn. The pre-existing modification to the author-environment skill is excluded.
