# Workbench cleanup

`scene.yaml` is a shared scene include. Load `task_1.yaml`, `task_2.yaml`, or
`task_3.yaml` with `ArenaEnvGraphSpec.from_yaml`; each defines a sequential task
using the same scene. The embodiment is `no_embodiment`.

Source credits: [NVIDIA SimReady assets](https://huggingface.co/datasets/nvidia/simready-assets),
[ForgeCAD](https://huggingface.co/datasets/ForgeCAD/simready-assets)
(`ratchet_socket_set`, CC BY 4.0; physics adapted here), and
[PalatialSim](https://huggingface.co/datasets/PalatialSim/palatial-nv-asset-library)
(`D00814`). Exact source revisions are pinned in `scene.yaml`.

The pinned SimReady Central packages provide the blue workbench, ratchet socket
set, oscilloscope, wall outlet, storage bin, three screwdrivers, and two sizes of
combination wrench. Five `clutter_on` relations release the tools over the middle
of the tabletop. The force demo uses placement seed 17.

The workbench has four prismatic drawers and a hinged cabinet door. Its original
blue overhead bins belong to the main workbench mesh and cannot be picked up
independently. The separate gray SimReady bin occupies the empty rack slot.
`assets.py` adds placement supports, retains the socket inserts with fixed joints,
exposes the case hinge and power button, and holds the outlet cap open. The
workbench frame and top drawer use compound collision panels because the source
SDF traps objects in empty workspace. The complete socket set uses separate base and lid
box colliders with inset contact surfaces; its detailed source colliders also
prevented lifting. Hand tools use convex hull contacts instead of their unstable
source SDFs; their visible meshes are unchanged. The case
is scaled to 90% to fit the drawer. Downloaded models and generated USD wrappers
stay in the user cache.

Tasks reuse `CloseDoorTask`, `OpenDoorTask`, `GoalPoseTask`, `ObjectInTask`, and
`PressButtonTask`. `ClosedCaseInDrawerTask` adds articulated-case bounds to the
existing containment, contact, and settling checks. `ToolInBinTask` uses the
actual tool hull because rotated enclosing-box corners extend below resting
tapered tools. Both retain ObjectInTask contact and settling checks. `UnplugTask`
requires a previously seated and aligned plug to be withdrawn and stopped. Final-state
requirements keep the case closed and contained, the drawer closed, and all five
tools inside the returned bin; intermediate drawer-open and bin-on-table states
need not remain true.

The pressed power button represents the device's off state. The force demo darkens
the source screen when that condition is met; no electronics are simulated. The
removable plug is a small procedural adapter; the cable is visual, without
flexible-body or electrical simulation.

## Force demo and teleoperation

Discover this clone's running container with the `dev-container` skill. Run as
the host user in `/workspaces/isaaclab_arena`:

```bash
HF_HUB_CACHE="$HOME/.cache/arena-workbench-hf" \
  ./submodules/IsaacLab/isaaclab.sh -p \
  isaaclab_arena_environments/workbench_cleanup/force_demo.py --task 1 --visualizer kit
```

Change `--task` to 2 or 3. `--interactive` enables viewport mouse-force operation.
`--commands path/to/operator.jsonl` reads live operator commands instead of the
built-in sequence. Commands include `move`, `joint`, `release`, `wait`, `inspect`,
`mark`, `check`, and `finish`. A move uses a bounded physical wrench and a joint
command uses effort control; neither writes an object pose during the task.
For example:

```json
{"action":"joint","name":"left_drawers","joint_name":"joint_drawersA_01_joint_00","goal":0.245,"seconds":3,"gain":300,"damping":50,"limit":70}
```

Outputs go to `artifacts/workbench_cleanup/task_N/`: `demo.mp4`, subtask boundary
PNGs, `progress.json`, and `validation.json`. The process asserts final task
success instead of declaring completion from the command list. Use Fabric
synchronization when rendering these nested SimReady physics assets.

## Recorded validation

All three tasks passed their final Arena success predicates using command-driven
force teleoperation in Isaac Sim, with no robot. The top-left drawer was opened,
loaded, and closed; the separate gray bin was picked up, packed with all five
tools, and returned to the rack. The other three drawer joints were inspected
but were not exercised through complete task sequences.

| Task | Completed subtasks | Boundary images | Recording |
| --- | ---: | ---: | --- |
| Socket set into drawer | 4 | 8 | [Task 1 GIF](../../docs/images/workbench_cleanup/task_1/demo.gif) |
| Tools into overhead bin | 7 | 14 | [Task 2 GIF](../../docs/images/workbench_cleanup/task_2/demo.gif) |
| Device off and unplugged | 2 | 4 | [Task 3 GIF](../../docs/images/workbench_cleanup/task_3/demo.gif) |

The [combined captioned GIF](../../docs/images/workbench_cleanup/workbench_cleanup_demo.gif)
runs for 2 minutes 12 seconds. The [media viewer](../../docs/images/workbench_cleanup/index.html)
shows the recording and every start/end image.
