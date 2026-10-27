# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Compatibility entry point for the maintained SimApp server."""

from isaaclab_arena.agentic_environment_generation.simapp.server import main

__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
