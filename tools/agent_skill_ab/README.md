# Agent-skill A/B pilot harness

This harness runs the collision-visualization authoring pilot in isolated, gitless repository
snapshots. It compares a control commit with a treatment commit while preserving raw Codex output,
filesystem audits, screenshots, and an independently measured wall-clock duration.

The timed Codex session diagnoses and repairs the environment but does not run OpenPI. Policy
acceptance is a separate, untimed harness phase so policy inference does not affect Codex session
measurements.

## Run

Start a compatible `pi05` OpenPI server on `127.0.0.1:8000`, then run:

```bash
python tools/agent_skill_ab/prepare_snapshots.py
python tools/agent_skill_ab/run_pilot.py
python tools/agent_skill_ab/run_acceptance.py
python tools/agent_skill_ab/summarize.py
```

Generated snapshots, randomized arm order, raw outputs, acceptance results, and the report are
written below `artifacts/codex_collision_viz_ab/` and must not be committed.

## Isolation

Each arm receives only its gitless snapshot, an empty result directory, the read-only harness,
shared simulation caches, and a fresh Codex home. The original checkout and Docker socket are not
mounted. Codex runs as the entrypoint-created host user through `sudo`, preserving its `isaac-sim`
supplementary group.
