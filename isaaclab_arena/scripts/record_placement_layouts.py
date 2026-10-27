# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Record root poses that pass post-physics placement checks."""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from pathlib import Path

from isaaclab_arena.offline_placement.recording import record_placements_to_jsonl, record_settled_placement_layouts
from isaaclab_arena.offline_placement.recording_config import load_recording_config

__all__ = ["record_placements_to_jsonl", "record_settled_placement_layouts"]


def main() -> None:
    """Run offline recording with Hydra settings and Isaac Lab launcher flags."""
    from isaaclab.app import AppLauncher

    from isaaclab_arena.utils.hydra_overrides import assert_hydra_overrides
    from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext

    parser = argparse.ArgumentParser(description=__doc__)
    AppLauncher.add_app_launcher_args(parser)
    launcher_args, overrides = parser.parse_known_args()
    assert_hydra_overrides(overrides, parser)
    cfg = load_recording_config(overrides)
    assert not Path(cfg.output).exists(), f"Output already exists: {cfg.output}"
    with SimulationAppContext(launcher_args):
        summary = record_settled_placement_layouts(cfg, device=launcher_args.device)
        for reason, count in Counter(summary.rejections.values()).items():
            print(f"  Rejected {count}: {reason}")
        if summary.accepted < cfg.min_layouts:
            if summary.output is None:
                logging.error(
                    "No layouts were accepted; no recording was written (requested %d).",
                    cfg.min_layouts,
                )
            else:
                logging.error(
                    "Only %d of %d requested layouts were recorded: %s",
                    summary.accepted,
                    cfg.min_layouts,
                    summary.output,
                )
            return
        print(f"Saved {summary.accepted}/{summary.attempted} accepted layouts: {summary.output}")


if __name__ == "__main__":
    main()
