---
name: Authoring Tool Replay
overview: Design a leakage-controlled Codex CLI A/B replay benchmark comparing the baseline workflow with the combined Arena tooling and extended `author-environment` skill on workbench-authoring substeps.
todos:
  - id: freeze-treatments
    content: Freeze exact S0T0 baseline and S1T1 combined-treatment exports, scrub workbench solution leakage, and record all source/container/model hashes.
    status: pending
  - id: build-capsules
    content: Create independent visible fixtures and hidden oracles/scorers for asset discovery, T1–T5 substeps, and the optional integrated mini-workflow.
    status: pending
  - id: instrument-codex
    content: Build the Codex CLI replay runner with fresh ephemeral sessions, randomized treatment blocks, JSONL token/timing capture, process metrics, and guaranteed sidecar cleanup.
    status: pending
  - id: pilot-freeze
    content: Run two pilot replicates per arm, repair benchmark-only defects, then freeze prompts, budgets, scorers, and leakage checks before collecting final data.
    status: pending
  - id: run-analyze
    content: Run the predeclared replicates, score blind outputs, compute A/B effects and confidence intervals, and publish success, quality, time, token, and process results without excluding failures.
    status: pending
isProject: false
---

# Arena Authoring Replay A/B Plan

## Objective and hypotheses

Measure whether the M1–M4 sidecar/CLI implementation in [`isaaclab_arena/scripts/arena_author.py`](isaaclab_arena/scripts/arena_author.py) and the extended [`skills/developer/author-environment/SKILL.md`](skills/developer/author-environment/SKILL.md) improve Codex success, elapsed time, and token use on independently replayable workbench-authoring substeps.

Treat the historical 2 h 25 min run in [`isaaclab_arena_environments/workbench_cleanup/CONSTRUCTION_AND_VALIDATION.md`](isaaclab_arena_environments/workbench_cleanup/CONSTRUCTION_AND_VALIDATION.md) only as motivation and calibration—not as an A/B sample—because it reused earlier search artifacts and ran on different code/context.

Primary hypotheses:
- Tooling improves success and time-to-correct-artifact for T1–T5 tasks.
- The extended skill improves tool discovery, command selection, cleanup, and interpretation.
- Structured reports reduce simulator retries, large-log reads, and uncached/context tokens.

## A/B treatments

Run every eligible experiment in two conditions:
- `S0T0`: baseline skill blob from `80e62cea9f^`; Arena authoring CLI/sidecar unavailable.
- `S1T1`: current extended skill and M1–M4 tooling available.

Build immutable source exports rather than ordinary git worktrees so Codex cannot recover the final solution from history:
- Start from one recorded Arena/Lab dependency lock and container image.
- Remove `.git`, all `workbench_cleanup` implementation/report/media, proposal text, prior transcripts, and generated artifacts from agent-visible trees.
- Overlay only the fixture files required by each experiment.
- `T0` uses a reverse feature patch for commits `579590335c` through `a2d143cfe5`; `T1` uses the full implementation. Record the resulting tree hash.
- Mount exact skill files, not paraphrases. Give each arm a neutral capability manifest stating only whether `arena_author.py` exists and where; do not include command recipes.
- Audit shell/import events and invalidate runs that use disabled tooling or inspect hidden oracle data.

The current implementation deliberately excludes T6 asset search and T7 Blender. Therefore asset *discovery* tests the combined workflow but must not attribute gains specifically to the CLI; asset *inspection* directly exercises the combined skill/tool treatment.

## Codex state and runner controls

Use OpenAI Codex CLI non-interactively:
- Pin the exact Codex CLI build, model, reasoning effort, sandbox policy, and Arena container digest.
- Start each run with a new exported workspace, fresh `CODEX_HOME`, `codex exec --json --ephemeral`, no resumed thread, no prior messages, no MCP tools, no web, and no human follow-up.
- Use identical prompts, writable paths, CPU PhysX settings, cached USD packages, placement seed, time budget, and command budget across arms.
- Pre-populate the same asset cache in every condition to remove network/download variance.
- Primary runtime condition: the S1T1 sidecar is already warm and S0T0 has equivalent simulator readiness. Run a smaller cold-start stratum to report startup overhead separately.
- Randomize S0T0/S1T1 order within replicate blocks; never run all baselines first. Use isolated sockets/output directories and force cleanup after every run.
- Pilot with two runs per arm. After fixing benchmark defects, run at least six fresh replicates per arm for core experiments; use three per arm for the media experiment. Do not mix pilot and final estimates.

Capture the Codex JSONL event stream, final response, file diff, stdout/stderr, monotonic start/end times, process tree, and command events. Read cumulative usage from `turn.completed.usage`: input, cached input, cache-write input, output, and reasoning-output tokens. Smoke-test the pinned CLI first and mark unavailable fields `null`, never zero.

## Experiment 0: Asset discovery and capability triage

Purpose: measure the skill's help in finding plausible assets and rejecting fused/non-detachable components; this is not a test of the implemented sidecar.

- Feature state: compare S0T0 with S1T1, but interpret any difference as a combined workflow effect because T6 search is absent.
- Input/state: original asset requirements only; a frozen local SimReady search-result corpus and package cache; no prior search JSON, workbench files, or internet. Ask Codex to select a bench, movable bin, hinged case, pressable device, outlet, and five tools, with evidence and pinned source IDs.
- Hidden oracle: candidate capability labels from the historical run—drawer joints, fused blue bins, independent replacement bin, hinged case, physical button, and no detachable electrical behavior.
- Quality: precision/recall of capability claims, correct unknown/unsupported labels, pinned reproducible sources, and no image-only physics claims.
- Efficiency: wall time, tokens, files/packages inspected, duplicate searches, and simulator startups. A simulator start for metadata-only triage is a process-quality penalty.

## Experiment 1: Static asset-physics inspection (T1)

- Feature state: S1T1 may use `asset inspect`; S0T0 may use existing USD helpers or write bounded inspection code.
- Input/state: a fixed set of anonymized source USD entry points for bench, bin, case, tool, and device; identical variants/cache; no environment YAML or prior inspection reports. Ask for one structured report per asset and a capability recommendation.
- Hidden oracle: body/joint graph, articulation roots, collider ownership, limits, disconnected case inserts, fused bin membership, units, and known unsupported geometry.
- Quality: exact topology/collider findings, provenance, unsupported-vs-passed correctness, machine-readable output, and absence of source mutation.
- Efficiency: time to first valid report, total time, tokens, USD files/bytes read, ad hoc scripts written, failed commands, and Kit startups. Record sidecar cache hits separately.

## Experiment 2: Bounded runtime physics diagnosis (T1)

- Feature state: S1T1 exposes `asset probe`; S0T0 receives the same runnable scene but must diagnose through existing APIs.
- Input/state: two short failing capsules derived from historical failures: visually empty drawer blocked by collision geometry, and a case with disconnected/unstable inserts. Provide the failing graph and a precise question; cap simulation to five minutes and forbid task completion work.
- Hidden oracle: root cause, offending prim/body/collider, measured displacement/contact evidence, and minimal repair class. Keep the corrected fixture hidden for replay verification.
- Quality: correct root cause and prim ownership, measured evidence rather than speculation, minimal non-destructive fix, and successful hidden replay after applying the proposed patch.
- Efficiency: diagnosis time, simulator restarts, probe attempts, physics steps, log volume read, tokens, and false leads. Score fast unsupported/failure reports above silent false passes.

## Experiment 3: Scene relation preflight (T3)

- Feature state: S1T1 may use `scene check`; S0T0 uses existing placement validation/recording paths.
- Input/state: a partial shared scene containing tabletop/rack/drawer references and deliberately faulty `on`/`clutter_on` settings (support height, edge margin, one stale reference). No tasks or asset repair work. Ask Codex to diagnose and minimally repair the scene, then produce three accepted distinct layouts.
- Hidden oracle: exact failed relation/reason, expected minimal YAML edits, distinctness threshold, required `on_relation`/`no_overlap`/post-physics outcomes, and a known-good replay set.
- Quality: schema validity, exact relation diagnostics, minimality, three genuinely distinct accepted layouts, explicit skipped checks, and replayability.
- Efficiency: time to first diagnostic and accepted layout, reset count, rejected samples, simulator startups, tokens, log reads, and number of YAML edits.

## Experiment 4: One force-operated subtask (T2)

- Feature state: S1T1 may use finite `force run` or a persistent force session; S0T0 may use existing environment APIs but receives no environment-specific force demo.
- Input/state: a frozen, already-buildable scene and one bounded goal: close the case, open the top-left drawer, insert the case, and close the drawer. Supply object/joint names and force limits, but no command stream or controller implementation. Exclude recording/media.
- Hidden oracle: native four-step progress, final current conditions, force/joint-hold cleanup, no pose teleportation, and timeout bounds.
- Quality gate: native success true, all historical and required current states correct, no root/joint holds, and trace proves physical commands. A fast failed run is not counted as an efficiency win.
- Efficiency: time-to-first completed command and native success, command retries, controller code added, physics steps, simulator restarts, tokens, and residual holds/timeouts.

## Experiment 5: Task-contract audit (T4)

- Feature state: S1T1 may use `task check`; S0T0 must use existing progress/predicate APIs without a supplied scenario runner.
- Input/state: completed task YAML plus frozen scenario recipes for initial, wrong-target, prepacked, complete, remove, replace, and reset states. Ask for an audit report only; do not author assets or motion recipes.
- Hidden oracle: expected native success, historical completion, required current-state truth, activation/entry behavior, containment geometry, and reset result for every case.
- Quality: scenario coverage, expected/actual verdicts, no mutation from diagnostic reads, exact containment/current-state explanation, and explicit incomplete/skipped cases.
- Efficiency: total scenario time, duplicate predicate evaluations, simulator resets, tokens, report parsing effort, and retries. Treat any diagnostic-induced progress change as a hard failure.

## Experiment 6: Evidence capture and publication input (T5)

- Feature state: compare S0T0 with S1T1, with three replicates per arm because media execution is comparatively deterministic and expensive.
- Input/state: a short successful two-boundary force trace and a fixed scene; ask for start/end/final frames, event-to-frame manifest, MP4, bounded GIF, and native-success evidence. Do not rerun the larger workbench workflow.
- Hidden oracle: boundary count/order, pre-autoreset final capture, frame timestamps, native result, media decodability, and byte limits.
- Quality: no missing/duplicated boundaries, success caption agrees with native termination, artifacts hash correctly, video/GIF decode, camera contains required objects, and GIF stays below budget.
- Efficiency: wall/encoding time, simulator steps, recaptures, FFmpeg retries, tokens, and custom publication code added.

## Experiment 7: Integrated mini-workflow

Use only after experiments 1–6 pass. This checks the combined workflow without recreating all 13 subtasks.

- Feature state: compare S0T0 with S1T1.
- Input/state: one unseen but workbench-like asset set; one shared scene; one three-step task; cached local assets; no solution files. Ask Codex to inspect, assemble, preflight, force-complete, audit one negative case, and capture three boundaries.
- Quality: weighted hidden checks from T1–T5, with hard gates on native success, physical execution, and truthful evidence.
- Efficiency: end-to-end wall time and tokens, plus phase breakdown. Limit to 30 minutes per run.

## Scoring and analysis

For every experiment, report separately:
- Success within budget and hard-gate failures.
- Blind quality score from automated hidden checks plus two reviewers who see outputs but not treatment. Resolve rubric disagreement before unblinding.
- Wall time to first correct diagnostic/artifact and total completion; report cold startup and warm execution separately.
- Input, cached input, uncached input, cache-write input, output, reasoning-output, and total tokens. Normalize tokens/time only among successful runs and also report a budget-censored result so fast failures cannot look efficient.
- Process metrics: simulator startups, CLI calls, failed commands, retries, files/bytes read, log volume, source lines added, reset count, physics steps, and cleanup violations.

Compute the predeclared A/B effect per experiment as `S1T1 - S0T0` for quality/success and the corresponding baseline-minus-treatment reduction for time/tokens. Describe it as the effect of the combined skill-plus-tooling package; do not claim separate skill or tooling causality.

Use medians and bootstrap 95% confidence intervals for time/tokens/quality, Wilson intervals for success rates, and time-to-success curves with budget failures censored. Publish all runs, including failures and outliers; do not pool experiments into one headline speedup unless hard-gate difficulty and weighting were predeclared.

## Benchmark artifacts and reproducibility

Document the design in [`docs/arena_authoring_ab_experiment_plan.md`](docs/arena_authoring_ab_experiment_plan.md). If implementing the harness, place versioned inputs and code under `benchmarks/arena_authoring_replay/`:
- `treatments/`: exact skill blobs, feature reverse patch, source/container hashes.
- `experiments/<id>/prompt.md`, visible fixture manifest, hidden oracle, scorer, and budgets.
- `run_codex.py`: fresh workspace/session setup, randomized blocks, JSONL capture, monotonic timing, cleanup, and protocol audit.
- `score.py`: hard gates and experiment rubrics.
- `analyze.py`: A/B effects, confidence intervals, and per-phase plots.
- `results/<run_id>/manifest.json`: treatment, prompt hash, model/CLI/container/source identities, timestamps, usage provenance, commands, artifacts, and score.

Keep hidden oracles outside agent-visible workspaces. Preserve failure artifacts. Before the final run, freeze prompts/scorers, run a leakage scan (`workbench_cleanup`, solution URLs, commit history, report phrases), and verify that both arms start from byte-identical experiment inputs except for the declared combined treatment.
