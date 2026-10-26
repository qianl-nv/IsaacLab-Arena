# Workbench cleanup: construction and validation report

The construction run on October 24, 2026 produced one shared scene, three
sequential task definitions, and successful force-operated demonstrations of all
13 subtasks. This report documents that run, including unsuccessful approaches
that explain the implementation and time spent. It was written on October 26
UTC from the saved session records, source files, and simulation artifacts.

## Original prompt

Original request, reproduced verbatim:

> Setup an arena environment for a workbench clean up task
>
> Use assets from SimReady Center.
> - Background is a blue workbench with drawers, hanging boards and overhead bins. Validate if the drawers are openable, and the overhand bins are pickable
> - On the surface of the workbench, right side have an opened ratchet_socket_set; middle has a cluttered piles of ~5 tools (screw driver, wrench ect), left has an electronic device with a on/off button (oscillascope, voltage meter, or heat gun ect), preferable with a power cord that can be plug in to an outlet <!-- codespell:ignore ect -->
> - set up the scene as one yaml with relations, use clutter on for the piles of tools
> - generate 3 task yamls using the same scene yaml.
>   task 1: close the socket set, open the top drawer on left, place the set inside the drawer, and close it
>   task 2: take a overhead bin onto the table, put tools into it, then put it back onto the top rack
>   task 3: turn off the elecronic device and unplug it from the outlet
> - For each task, write the compsite task with existing atomic task whenever possible; add atomic task only when necessary.  Validate with teleop that the task success condition are met, save an viewport image of the scene at each subtask start/end. generate a demo video showing the task completion using force (no actual robot) <!-- codespell:ignore compsite -->

## Execution time and token usage

**Total execution time excluding approval waits: 2 hours 25 minutes 13.973 seconds.**

| Measurement | Recorded value |
| --- | --- |
| Construction turn started | October 24, 2026, 16:29:08.473 UTC / 09:29:08.473 PDT |
| Final handoff completed | October 24, 2026, 18:54:22.446 UTC / 11:54:22.446 PDT |
| Elapsed wall time | 8,713.973 seconds |
| Approval wait subtracted | 0 seconds; no approval or user-input wait was requested |
| Model requests with usage records | 425 |
| Context compactions | 3 |
| Tool orchestration calls | 421 |

This is end-to-end wall time, including model processing, downloads, simulator
startup, tool execution, debugging, rendering, tests, and the final response.
It is not CPU time or the sum of overlapping subprocess durations. Earlier
search/smoke-test artifacts already existed when this turn began; their creation
time is outside this measurement. The later request to write this report and
the intervening days are also excluded.

| Token category | Tokens |
| --- | ---: |
| Input, including cached input | 59,563,056 |
| Cached input, included above | 58,499,456 |
| Uncached input | 1,063,600 |
| Output, including reasoning | 257,665 |
| Reasoning output, included above | 134,431 |
| **Total input + output** | **59,820,721** |

These are cumulative model-request counters, so repeatedly supplied context is
counted on every request. About 98.2% of input tokens were cached. Cached tokens
and reasoning tokens are subsets, not additional amounts to add to the total.
This is usage accounting, not a price estimate or a count of unique text.

The total was calculated by summing 425 unique `token_usage_record` entries for
the construction turn and checking the result against its final
`turn_token_usage`. It includes 754,183 tokens from three context-compaction
requests. The separate live `token_count` counter ended at 59,066,538 and omitted
those requests, which explains the difference. The extracted timestamps,
counters, source identifiers, and accounting method are saved in
[construction_run_metrics.json](../../artifacts/workbench_cleanup/construction_run_metrics.json).
The full private session transcript is not copied into the repository.

## Arena skills and APIs used

The environment was authored directly through Arena's graph YAML and builder
APIs. No skill named `make-arena` was invoked. The construction workflow used
these existing skills:

| Skill | Use in this run |
| --- | --- |
| [author-environment](../../skills/developer/author-environment/SKILL.md) | Discover existing examples, relations, affordances, tasks, and progress semantics; add narrow extensions only for demonstrated gaps. |
| [dev-container](../../skills/developer/dev-container/SKILL.md) | Discover the clone's running Docker container and execute simulation commands as the host user through the Isaac Lab launcher. |
| [run-tests](../../skills/developer/run-tests/SKILL.md) | Apply the simulation-aware testing workflow to focused graph and predicate checks. The complete three-phase suite was not run. |

The principal construction and validation APIs were:

| Area | Existing API or mechanism |
| --- | --- |
| Scene loading | [`ArenaEnvGraphSpec.from_yaml()` and `.to_arena_env()`](../../isaaclab_arena/environment_spec/arena_env_graph_spec.py), with `external_yaml: scene.yaml` in each task. |
| Environment creation | [`ArenaEnvBuilder.build_env_cfg()` and `.make_registered()`](../../isaaclab_arena/environments/arena_env_builder.py), followed by `env.reset()` and explicit `env.unwrapped` access. |
| Asset preparation | SimReady Central search results and its search endpoint, pinned package URLs, [`_download_central_asset_package_to_cache()`](../../isaaclab_arena/assets/simready_central_asset_loader.py), `SimReadyUsdObject`, and USD/PhysX inspection. The download helper is private; using it here is an integration limitation. |
| Layout | Existing `on`, `clutter_on`, and `is_anchor` relations; object references to support surfaces and the moving drawer link. |
| Affordances and registration | `Openable`, `Pressable`, `@register_asset`, `@register_task`, and the existing `NoEmbodiment`, newly exposed through the asset registry. |
| Atomic tasks | `CloseDoorTask`, `OpenDoorTask`, `GoalPoseTask`, `PressButtonTask`, and `ObjectInTask` as the base for containment adaptations. |
| Task composition | [`CompositeTaskBase`](../../isaaclab_arena/tasks/composite_task_base.py), `CompletionCriteria`, `TrueForConsecutiveStepsCfg`, progress tracking, and `task_success_from_progress`. |
| Force control | Isaac Lab's `ImplicitActuatorCfg`, `set_joint_effort_target()`, and `permanent_wrench_composer.set_forces_and_torques_index()`. |
| Capture | Kit viewport capture through `capture_viewport_to_buffer`, ImageIO video writing, and FFmpeg for the combined captioned video. |

The maintained examples consulted included
[the RoboLab tools scene](../robolab/scenes/tools_container.yaml),
[its sequential task example](../robolab/tasks/banana_then_rubiks_cube.yaml), and
[the clutter scene](../clutter/franka_three_hammers_and_clamp_no_task.yaml).
No policy server or robot-policy experiment was needed.

## Construction process

1. **Recover discovery results and inspect capabilities.** Reused the saved
   SimReady search results, corrected a download-cache permission problem, and
   inspected rigid bodies, joints, bounds, and physics variants. The blue NVIDIA
   workbench has four prismatic drawers with approximately 25 cm travel. Its
   original blue overhead bins are part of the main mesh, so they cannot be
   picked independently. A separate PalatialSim `D00814` bin fills the empty rack
   slot. The exact ForgeCAD `ratchet_socket_set` has a hinged lid. An NVIDIA
   oscilloscope supplies a physical button joint; an NVIDIA wall outlet supplies
   the socket geometry. See the [asset manifest](../../artifacts/workbench_cleanup/assets.json),
   [main inspection](../../artifacts/workbench_cleanup/asset_inspection.json),
   and [bin/cord inspection](../../artifacts/workbench_cleanup/extra_inspection.json).

2. **Author the shared relational scene.** [scene.yaml](scene.yaml) places the
   open case on the right, the oscilloscope on the left, and five loose tools in
   the middle using five `clutter_on` relations. Explicit tabletop, clutter-area,
   and rack references provide placement surfaces. Measured heights and a
   smaller rack edge margin corrected failed support checks. The drawer is a
   live link reference, not an independently reset rigid object. All three task
   YAMLs include this scene. The demonstrations use one CPU environment,
   placement seed 17, Fabric synchronization, and no robot embodiment.

3. **Adapt the source physics.** [assets.py](assets.py) retains the original
   visible geometry and drawer joints but replaces problematic collision shapes.
   The bench's SDF trapped props in visually empty space; whole-mesh convex
   decomposition also bridged openings. Separate frame panels and an open tray
   collider for the top-left drawer solved that problem. The socket case needed
   fixed joints to retain its fitted inserts, inset base/lid collision boxes,
   and 90% scale to fit. Small contact offsets prevented edge contact from
   reopening its lid. The loose tools needed convex hull contacts instead of
   unstable source SDFs. Downloaded packages and generated USD wrappers remain
   in the user cache, outside the source tree.

4. **Define composite task semantics.** [task_1.yaml](task_1.yaml) has four
   steps, [task_2.yaml](task_2.yaml) has seven, and [task_3.yaml](task_3.yaml) has
   two. A small schema/conversion change exposes Arena's existing
   `desired_subtask_success_state` through YAML. The drawer-open and bin-on-table
   steps are historical milestones; the final state must keep the case closed
   and contained, the drawer closed, and every tool inside the returned bin.
   [tasks.py](tasks.py) adds only the missing specializations: articulated closed
   case containment, exact tool-hull containment, and withdrawal of a previously
   seated plug. The containment adaptations retain contact and settling checks.

5. **Operate and diagnose the tasks.** [force_demo.py](force_demo.py) applies
   bounded physical wrenches and joint efforts. Validation used live JSONL
   operator commands, not a human mouse-teleoperation session. During task
   execution, object motion came from forces rather than pose teleportation.
   Debugging distinguished collision blockage from force-application and
   transform-synchronization problems. Light screwdrivers needed enough force
   to escape from under a heavier wrench. The loaded bin had to move forward
   before rising, and its orientation goal had to remain fixed across movement
   segments. A run with all historical steps complete still failed the final
   audit; that failure led to the corrected, successful bin recording.

6. **Validate and package evidence.** Each subtask start/end was captured from
   the simulator viewport. Final reports evaluate Arena's required current
   conditions as well as historical completion. The device demo darkens the
   screen after the button criterion succeeds and withdraws the plug along the
   outlet axis. Recordings were refreshed after the final collision and display
   fixes. FFmpeg combined them, added captions, and decoded the result to check
   playback. A separate built-in bin replay also passed. The artifact viewer
   presents all 26 boundary images next to their task evidence.

## Validation results and output artifacts

Media copies and the gallery are stored under `docs/images/workbench_cleanup`.
The four videos are provided as looping GIFs, each smaller than 10 MB
(10,000,000 bytes). All 27 PNGs retain their original resolution. The original
MP4s, JSON reports, commands, and logs remain under `artifacts/workbench_cleanup`;
include that directory when sharing the supporting run data outside this checkout.

- [Combined captioned GIF](../../docs/images/workbench_cleanup/workbench_cleanup_demo.gif)
  — 132.00 seconds, 640 × 360, approximately 6 fps, 7.66 MB.
- [GIF and boundary-image gallery](../../docs/images/workbench_cleanup/index.html).
- [Initial scene viewport](../../docs/images/workbench_cleanup/scene.png).
- [Aggregate validation report](../../artifacts/workbench_cleanup/validation_summary.json).

| Task | Result | GIF | Predicate report | Boundary timeline | Operator commands |
| --- | --- | --- | --- | --- | --- |
| Close case, open drawer, insert case, close drawer | 4/4; final success true; 8 images | [29.26 s; 7.33 MB](../../docs/images/workbench_cleanup/task_1/demo.gif) | [JSON](../../artifacts/workbench_cleanup/task_1/validation.json) | [8 events](../../artifacts/workbench_cleanup/task_1/progress.json) | [JSONL](../../artifacts/workbench_cleanup/task_1/operator.jsonl) |
| Bring bin down, pack five tools, return loaded bin | 7/7; final success true; 14 images | [93.34 s; 6.75 MB](../../docs/images/workbench_cleanup/task_2/demo.gif) | [JSON](../../artifacts/workbench_cleanup/task_2/validation.json) | [14 events](../../artifacts/workbench_cleanup/task_2/progress.json) | [JSONL](../../artifacts/workbench_cleanup/task_2/operator.jsonl) |
| Turn device off, unplug | 2/2; final success true; 4 images | [9.51 s; 2.19 MB](../../docs/images/workbench_cleanup/task_3/demo.gif) | [JSON](../../artifacts/workbench_cleanup/task_3/validation.json) | [4 events](../../artifacts/workbench_cleanup/task_3/progress.json) | [JSONL](../../artifacts/workbench_cleanup/task_3/operator.jsonl) |

Task 1 and task 3 GIFs use 960 × 540 at approximately 8 fps; task 2 uses
640 × 360 at approximately 6 fps. The complete recorded sequences are retained.
Frame resampling and GIF timing precision add less than 0.1 second to each
original recording's duration.

The timeline files name every numbered start/end PNG. The gallery links those
full-resolution files. Original run logs are available for
[task 1](../../artifacts/workbench_cleanup/task1_final.log),
[task 2](../../artifacts/workbench_cleanup/task2_final.log), and
[task 3](../../artifacts/workbench_cleanup/task3_final.log).

Focused verification produced
[73 passing graph/schema/conversion tests](../../artifacts/workbench_cleanup/graph_tests.log),
[one passing simulation-backed predicate test](../../artifacts/workbench_cleanup/predicate_tests.log),
and [passing pre-commit checks](../../artifacts/workbench_cleanup/lint.log).
The predicate test covers invalid seated/withdrawn plug states, case containment
and lid state, and false containment rejection from rotated enclosing boxes. The
[built-in bin replay report](../../artifacts/workbench_cleanup/diagnostics/scripted_replay/task_2/validation.json)
also records final success.

One existing generic SimReady fresh-process loader test failed on missing
`usd_path`, including in an isolated run; it was excluded from the passing graph
run. Its [failure log](../../artifacts/workbench_cleanup/isolated_existing_test.log)
is retained. A combined test invocation also crashed during simulator startup,
so the predicate test was rerun separately. The full three-phase suite was not
run. Successful teleoperation at this seed establishes task feasibility, not
robustness over all clutter seeds or robot reachability.

The top-left drawer was physically opened, loaded, and closed. The other three
drawer joints were inspected but not exercised through complete sequences.
The original blue bins remain fixed; the gray bin is the validated movable
substitute. The plug is procedural, the cord is visual, and the pressed button
represents OFF; electrical behavior and flexible cable physics are not modeled.

## Five most time-consuming steps

These are approximate **dominant-work phase durations**, reconstructed from
timestamped progress messages and run logs. The UTC windows partition the
measured construction turn. They are not per-function profiler measurements:
tests, downloads, documentation, and device work sometimes ran inside another
phase. Rounded durations sum to the approximately 2 h 25 min total.

| Rank | Dominant work | Approximate wall time | UTC window, October 24 | Why it took time |
| --- | --- | --- | --- | --- |
| 1 | Drawer/case physics, force control, and containment debugging | 1 h 9 min 52 s | 16:56:28–18:06:20 | Nested-asset transform synchronization, passive-joint actuation, bench SDF blockage, unsuitable whole-mesh convex replacement, case collision blockage, drawer tray geometry, lid reopening, and contact/settling failures required repeated simulation probes. |
| 2 | Tool extraction, bin packing, final-state audit, and device checks | 38 min 30 s | 18:06:20–18:44:50 | Unstable tool SDFs, a light tool pinned by a heavy wrench, false enclosing-box corners, a perched wrench, and loaded-bin tilt required controller and predicate corrections. Device recording and focused tests overlapped this phase. |
| 3 | Shared scene, task integration, and initial build/placement validation | 18 min 39 s | 16:37:49–16:56:28 | Support bounds, tabletop height, edge margins, articulated references, joint-limit cleanup, and YAML final-state semantics had to agree before a reliable reset. |
| 4 | Final reruns, artifact packaging, and replay verification | 9 min 32 s | 18:44:50–18:54:22 | Refreshing recordings after fixes, screen-material correction, caption placement, full video decoding, gallery creation, and a final built-in bin replay. |
| 5 | Asset discovery recovery, capability inspection, and initial preview | 8 min 41 s | 16:29:08–16:37:49 | Cache permissions, package downloads, articulation inspection, finding a movable substitute bin, and checking that electrical assets lacked detachable cable/plug behavior. Earlier saved searches were reused. |

Representative troubleshooting evidence includes the
[world-frame probe](../../artifacts/workbench_cleanup/diagnostics/logs/world_frame_probe.log),
[later drawer probe](../../artifacts/workbench_cleanup/diagnostics/logs/task1_debug11.log),
[bin calibration commands](../../artifacts/workbench_cleanup/diagnostics/task2_calibration_commands.jsonl),
and [placement diagnostic](../../artifacts/workbench_cleanup/diagnostics/logs/placement_diagnostic.log).
Diagnostic attempts are not counted as successful final demonstrations.

## Arena additions that could speed up similar work

The following are proposed additions, not claims that these commands or
capabilities already exist. They should extend the current APIs and skills.
No measured speedup is claimed.

| Priority | Proposed tool, CLI, API, or skill addition | What it would have shortened here |
| --- | --- | --- |
| 1 | An asset-physics inspection CLI built on existing preparation/geometry APIs: body/joint topology, collision overlays, limits, mass/inertia, contact reports, and bounded force probes. Include reusable open-tray and articulated-case collider adapters. | Detect collision shapes occupying empty workspace before full task authoring; distinguish stuck geometry from a broken force controller; expose the case's disconnected inserts and passive joints immediately. |
| 2 | A maintained force-teleoperation/validation mode in the environment runner, extracted from `force_demo.py`: bounded movement and joint commands, stable orientation goals, live contact/velocity/predicate traces, and final-state assertions. Pair it with a focused skill. | Avoid implementing and repeatedly tuning an ad hoc operator; diagnose pinned tools and settling failures; catch historical-completion versus current-success differences before recording a full run. |
| 3 | A single-scene preflight CLI that reuses the placement validation APIs, plus general containment support for articulated objects and actual transformed hulls. Report the exact support/edge-margin failure and resolve live articulation-link references. | Reduce failed build/reset cycles and remove the need for the two environment-specific containment adaptations. Extend existing placement validation rather than duplicate its solver. |
| 4 | A shared task-recording API that captures start/end viewports from progress events, checks required final conditions, and exports captions, a gallery, and a validation manifest in one operation. | Replace custom viewport capture and repeated report/video assembly; prevent caption and screenshot timing mistakes; make every demonstration reviewable by default. |
| 5 | Capability-oriented SimReady search/inspection with a public cached-package API: detachable versus fused components, openable joints, pressable controls, usable container interior, and available cable/plug articulation. Allow static USD inspection without starting SimulationApp. | Reject fused bins and non-detachable electrical assets earlier; avoid repeated package listings and private-helper/cache overrides; avoid simulator startup for purely static metadata questions. |

The first two phases account for about 75% of the measured wall time, making
asset-physics diagnostics and reusable force validation the strongest initial
priorities. Structured summaries from those tools would also reduce repeated
large USD/log reads and the context carried through hundreds of model requests.
A small run manifest recording phase timestamps, approval intervals, and usage
counter provenance would make future timing reports automatic.

See [README.md](README.md) for the supported environment loading and replay
commands. This report adds documentation and accounting evidence; it does not
change the validated scene, task definitions, or runtime behavior.
