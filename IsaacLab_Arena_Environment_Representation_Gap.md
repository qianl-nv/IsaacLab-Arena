# Isaac Lab–Arena Environment Representation Gap Analysis

## Purpose

This document identifies what must be specified or implemented before Arena can remove:

- `ArenaEnvironmentFactory`
- the `ArenaEnvironmentCfg` base class
- `IsaacLabArenaEnvironment`
- the Arena `EnvironmentRegistry`
- `ArenaEnvBuilder`

It complements `Isaac Lab _ Arena Environment Representation.md`. That proposal gives the intended
direction—Arena becomes a compiler/materializer plugin that produces an ordinary Isaac Lab
environment configuration—but it does not yet define a complete replacement for every
responsibility owned by the five abstractions above.

## Target architecture

The target should have one public execution path:

```text
Gym task id
  -> serializable source configuration
  -> Isaac Lab applies presets and Hydra/CLI/programmatic overrides
  -> Arena materializer runs once
       -> resolve registered Arena assets/tasks
       -> solve relations and placement
       -> apply build-time variations
       -> compose scene and manager terms
       -> select physics and rendering configuration
  -> complete ManagerBasedRLEnvCfg
  -> stock ManagerBasedRLEnv
  -> standard Isaac Lab workflow
```

Arena graph YAML and Python-authored tasks should enter the same materialization boundary. They may
have different source schemas, but they should not have different runtime construction paths.

## Replacement map

| Removed Arena abstraction | Responsibilities today | Replacement |
| --- | --- | --- |
| `ArenaEnvironmentFactory` | Owns registries and turns a task-specific typed config into live scene, embodiment, and task objects | A task-specific materializer function registered through Isaac Lab's `env_cfg_materializer_entry_point`. Shared Arena compiler functions perform asset resolution, relation solving, and term composition. Registry access is explicit or supplied through an `ArenaCompilationContext`; it is not stored on a factory instance. |
| `ArenaEnvironmentCfg` base | Marks environment config types, contributes `enable_cameras`, and lets the EnvironmentRegistry infer a factory/config pairing | A concrete source config per Gym task. It is either a `ManagerBasedRLEnvCfg` subtype with a serializable Arena source section, or a separate serializable Arena source model accepted by a generic registered cfg wrapper. Camera selection belongs in an embodiment/sensor profile, not a universal Arena base class. |
| `IsaacLabArenaEnvironment` | Bundles name, `Scene`, embodiment, task, teleop, callback, RL metadata, recorder terms, placer parameters, and default backend | Serializable source data (`ArenaEnvGraphSpec` or task-specific source fields) plus local values produced during materialization. Runnable-task identity and RL entry points live in Gym registration; scene/task/embodiment objects are compiler-local; viewer, recorder, placement, and backend settings become typed config fields. |
| Arena `EnvironmentRegistry` | Maps environment name to factory and maps factory/config types in both directions | Gymnasium's task registry for runnable task IDs and their cfg/materializer/agent entry points. Arena keeps `AssetRegistry`, `TaskRegistry`, relation registries, and other component catalogs. Evaluation stores a Gym task ID and source overrides/spec directly instead of recovering a factory from the Python type of a config object. |
| `ArenaEnvBuilder` | Placement, variation setup, scene and manager-term composition, physics selection, recorder/metric setup, Gym registration, and environment creation | Stateless Arena compiler/materializer functions plus existing Lab APIs: `isaaclab.scene.add`, `isaaclab.managers.event_add`, `isaaclab_tasks.utils.parse_env_cfg` / `materialize_env_cfg`, Gym registration, and `gym.make`. Runtime-only behavior must move to Lab managers/terms or evaluation utilities before the stock runtime can be used. |

### Adjacent types

Removing `ArenaEnvBuilder` also requires a decision about `ArenaEnvBuilderCfg`. Its fields cannot
remain as configuration for a class that no longer exists. They should be split by ownership:

- scene batch settings: `env_cfg.scene`
- simulation settings: `env_cfg.sim`
- relation-placement settings: a typed Arena materialization section
- variation/replay settings: typed Arena materialization or run settings
- recording output and rollout limits: evaluation/run settings
- mimic selection: task/runtime registration, not a generic build boolean
- language instruction: task metadata on the completed environment config

`IsaacLabArenaManagerBasedRLEnvCfg` and `IsaacLabArenaManagerBasedRLEnv` are not in the stated removal
list, but the proposal's use of stock `ManagerBasedRLEnv` makes their removal or narrowing an
implicit dependency. This must be decided explicitly.

## What already exists

The proposal should distinguish implemented foundations from missing work.

### Isaac Lab APIs already available

- `isaaclab.scene.add` supports component composition with `mode="merge"`, conflict handling, and a
  mutable `bindings` map.
- `isaaclab.managers.event_add` appends ordered event terms and rejects duplicate names.
- Gym task registrations support `env_cfg_entry_point`.
- The checked-out Isaac Lab supports `env_cfg_materializer_entry_point`.
- `isaaclab_tasks.utils.materialize_env_cfg` guards materialization so it runs at most once.
- `parse_env_cfg` and Hydra task resolution apply overrides before materialization.

### Arena bridges already available

- `ArenaEnvironmentSourceCfg` is an interim unmaterialized configuration.
- `materialize_arena_environment_cfg` is an interim materializer.
- `ArenaEnvGraphSpec` is a serializable scene/task source for graph-authored environments.
- `environment_registration_callback` allows Isaac Lab scripts to discover legacy named Arena
  environments.

These are transition mechanisms, not the final architecture:

- `ArenaEnvironmentSourceCfg` hides a live `IsaacLabArenaEnvironment` in a dunder attribute.
- `materialize_arena_environment_cfg` constructs `ArenaEnvBuilder` and calls its private
  `_compose_manager_cfg`.
- graph conversion still returns `IsaacLabArenaEnvironment`.
- the registration callback still resolves `EnvironmentRegistry` and an
  `ArenaEnvironmentFactory`.

## Gaps in the proposal

### 1. No canonical source representation is selected

The proposal alternates between three incompatible source forms:

1. `ArenaEnvGraphSpec` / YAML
2. task-specific fields directly on a `ManagerBasedRLEnvCfg`
3. the current live `Scene` + embodiment + task object graph

The final API must state which form is canonical and how the others lower into it. In particular:

- Define whether Python-authored environments must produce `ArenaEnvGraphSpec`, a typed source cfg,
  or another public Arena IR.
- Define how custom Python semantics that cannot be serialized in graph YAML are represented.
- Define whether the materializer mutates and returns the source cfg or returns a separate completed
  cfg.
- Require the pre-materialization source to be serializable, deep-copyable, and safe for Hydra.
- Eliminate `ArenaEnvironmentSourceCfg.__arena_environment__`; otherwise
  `IsaacLabArenaEnvironment` has only been hidden, not removed.

Recommended direction: use a concrete Lab environment cfg with a typed, serializable
`arena_source` section. `ArenaEnvGraphSpec` can be one supported value of that section. Keep
compiler-local live objects out of the public config.

### 2. The proposed config shape is internally inconsistent

The example declares fields such as `pick_up_object` directly on
`MapleTablePickPlaceEnvCfg`, but later writes `cfg.scene_source.pick_up_object`. No
`scene_source` field is declared.

The document must define one stable override path, for example:

```text
arena_source.pick_up_object
arena_source.destination
arena_materialization.placement.seed
scene.num_envs
sim.device
```

That path must work identically through Hydra, CLI overrides, Experiment YAML, and programmatic
configuration.

### 3. The programmatic lifecycle example materializes too early

In the checked-out Lab, `parse_env_cfg(...)` returns an already materialized config. Therefore this
sequence from the proposal is not valid:

```text
cfg = parse_env_cfg(...)
cfg.scene_source.pick_up_object = ...
env = gym.make(..., cfg=cfg)
```

Changing source fields after `parse_env_cfg` is too late, and `gym.make` does not itself invoke the
materializer. The supported alternatives must be documented and tested:

- pass source changes as `parse_env_cfg(..., overrides=[...])`; or
- load/resolve with `materialize=False`, change source fields, call `materialize_env_cfg`, then call
  `gym.make`.

Every Isaac Lab entrypoint used by Arena must be audited to ensure it invokes the materializer after
all source overrides and before environment construction.

### 4. The compiler API and intermediate state are unspecified

The pseudocode `compile(...)` returns an undefined `cfg` and does not identify where compiler-local
state lives. A concrete API is needed, for example:

```text
materialize_arena_env_cfg(source_cfg) -> ManagerBasedRLEnvCfg
compile_arena_graph(graph_spec, target_cfg, compilation_cfg) -> ManagerBasedRLEnvCfg
```

The contract must define:

- input and output types
- mutation versus copy semantics
- idempotence
- ownership and lifetime of instantiated assets
- diagnostics and failure reporting
- deterministic seed derivation
- what data may survive into runtime
- whether compilation may inspect USD or requires a running SimulationApp

The implementation currently concentrated in `ArenaEnvBuilder._compose_manager_cfg` must be
inventory-mapped and extracted before the builder can be deleted.

### 5. Scene-composition semantics are incomplete

The proposal shows `scene_add(scene, fragment)` without arguments. The current Lab default is
heterogeneous clone composition, not component merge. Arena needs:

```text
scene_add(target, source, mode="merge", on_conflict=..., bindings=...)
```

The design must choose and document:

- conflict policy (`"error"` should be the public default; intentional replacement should be
  explicit)
- whether source field names or Arena semantic IDs are binding keys
- namespace rules when scene, embodiment, and task fragments use the same field name
- how bindings are propagated into actions, observations, events, rewards, terminations, recorders,
  and predicates
- behavior for sensors, terrain, collections, global assets, and spawnless references
- behavior for heterogeneous scenes and object sets

The current builder uses `on_conflict="replace"`, which can silently let a later fragment replace an
earlier entity. The target contract should not inherit that behavior accidentally.

### 6. Manager-term binding is only pseudocode

The document proposes passing `bindings` to term producers, but current `Scene`, embodiment, and
task APIs mostly return fully formed cfg fragments. A migration contract is needed for:

- `get_observation_cfg`
- `get_action_cfg`
- `get_events_cfg`
- `get_rewards_cfg`
- `get_commands_cfg`
- `get_curriculum_cfg`
- `get_termination_cfg`
- recorder and mimic configs

Each producer must either accept semantic bindings or use a common binding resolver. Otherwise a
renamed scene entity can leave `SceneEntityCfg` references stale.

### 7. Event configuration initialization and ordering are underspecified

The proposed cfg sets `events = None` and later calls `event_add(env_cfg.events, ...)`, which
requires a dictionary target.

The replacement must preserve the current ordering invariants:

1. background physics restoration first
2. embodiment reset/events
3. scene/object events
4. task events
5. placement
6. runtime variations
7. progress/recording updates at their required lifecycle point

It must also define event naming/namespacing because Lab's `event_add` rejects duplicate term names.
Ordering should be an explicit compiler contract with tests, not an incidental tuple in one
materializer.

### 8. Relation placement has no complete replacement contract

The proposal mentions relation solving but omits several current behaviors:

- task reachability constraints are applied before placement
- live and recorded placement use different preparation paths
- `solve_relations`, `placement_seed`, and `resolve_on_reset` overrides
- fixed layouts versus reset-time sampling
- embodiment co-placement
- cuRobo availability and fallback behavior
- serialization and replay of placement samples
- object-set limitations for replay
- background-collision handling

These need a typed materialization config and a compiler result that can install the required reset
event without passing a builder-owned sampler through hidden state.

### 9. Variation state has no Lab-native runtime handoff

Runtime variation events can remain manager terms, but recording and deterministic replay currently
depend on live `VariationRecorder` and `VariationReplayScheduler` objects. The interim materializer
attaches them to private attributes on the completed cfg, and the Arena runtime removes them before
Lab validation.

A stock-runtime solution is required:

- make variation recording a RecorderManager term or another declared manager term
- make replay episode assignment/reset behavior a declared term or service with explicit lifetime
- define episode-index ownership
- avoid non-serializable private cfg attributes
- preserve release of per-episode samples and recorded-placement synchronization

Until this is solved, replacing `IsaacLabArenaManagerBasedRLEnv` with stock `ManagerBasedRLEnv` is
not behaviorally equivalent.

### 10. Arena-only runtime behavior is not fully migrated

The “Additional Arena Features” table is directionally correct but incomplete. The custom runtime
currently owns:

- `ArenaWorld`
- task progress tracking and once-per-control-step updates
- success termination derived from progress
- initial-rest-pose recording
- Arena recorder-manager substitution
- metrics manager and `compute_metrics`
- JSONL episode recording
- episode indices and a global episode budget
- active/inactive environment masking
- variation recording and replay scheduling
- language-instruction access

For each feature, the design needs a destination, migration owner, and compatibility test. Likely
destinations are Lab event/recorder terms, ordinary cfg metadata, and evaluation utilities over
recorded data. “Remove or replace” is not enough to establish parity.

### 11. Task registration and discovery are not defined

Gym registration can replace the Arena EnvironmentRegistry only after the following are specified:

- canonical, versioned task IDs
- where first-party registrations live and how they are imported
- how a dynamic `--env-spec path.yaml` becomes a task registration
- whether dynamic graph registrations are process-local and how IDs avoid collisions
- how external Python environments register without `external_environment_class_path`
- how RL agent cfg entry points are attached
- how task listing and help text discover Arena tasks without a temporary placeholder
- how duplicate registration and repeated experiment rebuilds are handled

The current `register_rl_discovery_placeholder` and external callback are compatibility mechanisms,
not a final replacement.

### 12. Typed Experiment configuration still depends on the removed registry

`ArenaRunCfg.environment` currently contains an `ArenaEnvironmentCfg`, and execution recovers a
factory through `EnvironmentRegistry.get_factory_type_for_cfg`. The typed YAML loader also obtains
environment schemas from that registry.

A replacement run schema is needed. A run should identify:

- the Gym task ID
- source overrides or an Arena graph-spec path/value
- materialization settings
- simulation/runtime overrides
- policy and rollout settings

The evaluation runner should resolve/materialize the task through the same Lab API as training,
rather than constructing `ArenaEnvBuilder` directly. Serialization and result metadata must use the
task ID/source spec instead of factory class names.

### 13. Gym registration metadata currently stored on `IsaacLabArenaEnvironment` needs a home

The following fields need explicit replacements:

- `name` -> Gym task ID
- `rl_framework_entry_point` and `rl_policy_cfg` -> Gym registration kwargs
- `default_physics_backend` -> a typed physics preset/default on the source cfg
- `env_cfg_callback` -> ordinary typed cfg values or a named compiler stage
- `episode_recorder_terms` -> recorder config/term composition
- `placer_params` -> typed Arena materialization config
- `teleop_device` -> Lab teleop/device config or a separate teleoperation workflow

Arbitrary post-compilation callbacks should not be the final API because they are hard to serialize,
order, validate, and expose through Hydra.

### 14. Physics, rendering, and process-global initialization are not integrated

`ArenaEnvBuilder` currently selects Arena physics presets, forces Newton scene replication, applies
global rendering settings, installs a Warp compatibility patch, converts legacy viewer settings,
and validates scene/backend compatibility.

The target design must define:

- use of Lab `PresetCfg` for physics and renderer selection
- where Arena global plugin initialization runs exactly once
- migration from `ViewerCfg` to `VisualizerCfg`
- when backend-specific asset configuration occurs
- where scene/backend validation runs
- ownership and removal criteria for compatibility patches

These behaviors cannot disappear merely because scene composition moves into a materializer.

### 15. Mimic and non-RL environments are not covered by the concrete design

The document says the representation should extend beyond RL and claims applicability to Direct
environments, but all concrete composition examples build manager terms for
`ManagerBasedRLEnvCfg`.

The scope must state one of:

- phase one supports only manager-based RL/evaluation environments; or
- define separate materializer contracts for `ManagerBasedRLMimicEnvCfg`, `ManagerBasedEnvCfg`,
  and `DirectRLEnvCfg`.

Mimic also requires embodiment-specific runtime selection and task-provided datagen/subtask
configuration. A boolean `mimic` build option is not a sufficient registration model.

### 16. First-party and external authoring migration is not planned

The repository has many first-party modules using the factory/config/decorator pattern. A migration
must define:

- the new module template
- conversion of each factory `build` method into source config plus materializer logic
- replacement for legacy environment-specific argparse options
- compatibility for external environment packages
- deprecation period and error messages
- whether existing environment names remain aliases for new Gym IDs

Direct users of `ArenaEnvBuilder` in scripts, examples, tests, and notebooks also need a supported
replacement function, not only an internal rewrite.

### 17. Validation and acceptance criteria are missing

Removal should be gated by tests that demonstrate:

- source overrides are applied before exactly-once materialization
- graph and Python source forms produce equivalent completed cfgs
- scene bindings remain correct after name conflicts/renames
- event order is stable and duplicate terms fail clearly
- placement is deterministic by seed and works at reset
- build-time and runtime variations retain recording/replay behavior
- PhysX and Newton presets remain valid
- camera, teleop, recorder, and mimic paths remain supported where promised
- training, evaluation, environment runner, and demo collection use the same task registration
- repeated builds do not leak live objects through Gym's process-global registry
- completed configs pass Lab validation and instantiate through stock runtime where intended

Static config comparison is insufficient; focused simulation tests are required for reset,
recording, placement, progress, and replay semantics.

## Required public API decisions

Before implementation, the proposal should resolve these decisions:

1. **Source type:** Is `ArenaEnvGraphSpec` the canonical source, or is there a generic typed
   `ArenaSourceCfg` that may contain a graph?
2. **Materializer signature:** What exact public Arena function does every task register?
3. **Completed cfg type:** Stock `ManagerBasedRLEnvCfg`, an Arena subtype with only declarative
   fields, or both during migration?
4. **Runtime:** Is stock `ManagerBasedRLEnv` required in this phase, or is the Arena runtime retained
   temporarily?
5. **Task identity:** What is the versioned Gym ID naming scheme?
6. **Dynamic graphs:** How does `--env-spec` register and resolve a task?
7. **Bindings:** What semantic key format is stable across scene fragments and manager terms?
8. **Compiler settings:** Which settings belong to source materialization versus evaluation?
9. **Runtime state:** Which Lab manager/term owns variation replay, progress, metrics, and episode
   bookkeeping?
10. **Compatibility:** What aliases and deprecation window are provided to existing users?

## Suggested migration sequence

1. Define the canonical serializable source schema and override paths.
2. Define a public, stateless Arena materializer/compiler API.
3. Extract compiler stages from `ArenaEnvBuilder` without changing behavior.
4. Move all runtime-only state into declared managers/terms or evaluation utilities.
5. Register one representative environment directly with Gym and the Lab materializer hook.
6. Make evaluation execute that task through `parse_env_cfg` and `gym.make`.
7. Add graph-spec registration through the same path.
8. Migrate the remaining first-party and external authoring surfaces.
9. Deprecate legacy names and adapters.
10. Remove the factory, base cfg, intermediate environment, EnvironmentRegistry, and builder only
    after no production path or compatibility test depends on them.

## Definition of done

The five abstractions can be removed when:

- no source config contains or reconstructs an `IsaacLabArenaEnvironment`;
- no runnable task is discovered through Arena's EnvironmentRegistry;
- no training, evaluation, teleop, recording, or test path constructs `ArenaEnvBuilder`;
- all task overrides occur on serializable source fields before materialization;
- all Arena compiler behavior is reachable through a registered Lab materializer;
- all promised Arena runtime features work through the selected Lab runtime and managers;
- graph YAML and Python-authored tasks share the same completed cfg and Gym execution path; and
- migration guidance exists for first-party and external environment authors.
