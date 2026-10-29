#!/usr/bin/env python3
# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Randomize and run the two timed Codex arms sequentially."""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "artifacts" / "codex_collision_viz_ab"
RUN_ARM = Path(__file__).with_name("run_arm.py")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, help="Optional reproducible arm-order seed")
    args = parser.parse_args()

    order = ["arm_amber", "arm_cobalt"]
    rng = random.Random(args.seed) if args.seed is not None else random.SystemRandom()
    rng.shuffle(order)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "order.json").write_text(json.dumps({"order": order}, indent=2) + "\n")
    for arm in order:
        subprocess.run([sys.executable, str(RUN_ARM), arm], check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
