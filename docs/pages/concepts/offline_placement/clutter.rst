Offline Clutter Settling
========================

``ClutterOn`` defines collision-checked release poses. Offline settling uses the
same reset, physics stepping and validation workflow as
:doc:`recording`. Each reset selects a solved layout from the placement pool.
Physics drops the objects, and the configured validators decide whether to keep
their final poses.

Collect layouts
---------------

Use the ordinary offline placement recorder. It detects ``ClutterOn`` relations,
runs clutter-specific preflight checks, and selects clutter validators before using
the shared reset, settling, validation, and JSONL-writing workflow:

.. code-block:: python

   from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
   from isaaclab_arena.environments.arena_env_builder_cfg import ArenaEnvBuilderCfg
   from isaaclab_arena.offline_placement.recording_params import PlacementRecordingParams
   from isaaclab_arena.scripts.record_placement_layouts import record_placements_to_jsonl

   params = PlacementRecordingParams(num_steps=480, min_layouts=1)
   env = ArenaEnvBuilder(arena_env, ArenaEnvBuilderCfg(num_envs=4)).make_registered()
   try:
       summary = record_placements_to_jsonl(
           env,
           "settled_clutter.jsonl",
           num_batches=2,
           params=params,
           render=True,
           scene_assets=arena_env.get_placement_assets(),
       )
       print(summary.accepted)
       print(summary.rejections)
   finally:
       env.close()

Run this after ``SimulationApp`` starts. Do not reset before collecting: collection
resets once per batch. Two batches of four environments sample eight candidates.
``num_steps`` counts environment steps, each containing the configured number of
physics substeps; it is independent of the number of batches.

The output uses the same episode JSONL format as ordinary settled placement
recordings. Each accepted record contains final root poses and the solver and
post-physics validation reports. If fewer than ``min_layouts`` candidates pass,
the recorder returns ``output=None`` and does not write a partial file.

The caller owns the environment. It remains at its final state after collection
or failure.

Acceptance checks
-----------------

The shared validator builder and evaluator run these defaults:

* ``physics_settled`` checks final root velocities for all measured objects.
* ``pose_shift`` limits other objects to 2 mm translation and 2 degrees rotation.
  Its clutter implementation excludes intentional ``ClutterOn`` drops.
* ``articulation_link_shift`` checks articulated task objects using the existing
  root-relative link check. Robot links are excluded, as in ordinary recording.
* ``support_containment`` checks that clutter stays within its support footprint
  and does not fall through it. It also requires successful release
  ``no_overlap`` and ``clutter_on_relation`` checks.

All enabled, applicable checks must pass. Disabled and inapplicable checks retain
their skip reasons. The recorder selects these defaults automatically. To customize
them, initialize ``params.validators`` with ``default_clutter_validators()`` and,
for example, set
``params.validators["support_containment"]["containment_margin_m"] = 0.005`` to
permit 5 mm overhang. Physics runs for the configured duration; final velocity
limits determine whether the objects are still moving.
Validators read captured measurements, without stepping physics or reading the
live environment themselves.

Scope and limitations
---------------------

Supports must be fixed anchors with a flat rectangular collision surface covering
the top face of their bounds. This is checked before the first reset. A whole tray
with a rim or a table with rails does not satisfy that assumption: its highest
point is not the resting surface. Use an ``ObjectReference`` to the Xform containing
only the tray floor or tabletop collider as the ``ClutterOn`` parent, and mark that
reference ``IsAnchor``. Author the reference's translate, orient and scale operations
before building the environment; rewriting a collider's transforms after physics
initialization can invalidate its physics view. Both release placement and settled
containment then use that surface's bounds. Cube colliders and connected planar
mesh facets are supported; curved surfaces and surfaces assembled from separate
coplanar colliders are not.

Clutter members must be dynamic rigid bodies with gravity enabled in every
selected object-set variant. Assign object-set variants
before scene construction. Other placement must already be resolved to fixed
anchors. Anchors, backgrounds and passive obstacles must match their configured
poses; pose-changing reset variations on this fixed geometry are unsupported.

Release generation uses normal placement's collision discovery, including MESH
background fixtures, per-asset collision modes, and anchored support exclusions.
Tilted clutter requires BBOX because the solver's mesh checks use yaw only.
Post-physics checks do not rerun collision or IK validation.

Assets marked ``RequiresReachability`` are rejected. Use a generation scene
without reachability requirements. Retain ``no_overlap`` and
``clutter_on_relation`` in its solver checks. Do not use the pre-physics
``physics_settled`` check on intentional release poses; the post-physics velocity
validator checks the dropped objects instead.

Physics also advances the robot. The recorder does not immobilize its joints,
and moving robot links can affect the objects. Only root poses are collected;
joint states are not recorded. Root speed and displacement remain checked.

The offline package depends on the solver and shared records. Online placement
and runtime replay do not import offline modules.
