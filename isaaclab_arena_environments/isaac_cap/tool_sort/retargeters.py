# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Teleop retargeters for the industrial tool-sort benchmark."""

from __future__ import annotations

from collections.abc import Callable

from isaaclab_arena.assets.retargeter_library import RetargetterBase


class IndustrialFr3RobotiqKeyboardRetargeter(RetargetterBase):
    """Route keyboard SE(3) commands directly to the industrial FR3 IK action."""

    device = "keyboard"
    embodiment = "industrial_fr3_robotiq_2f85_differential_ik"

    def get_pipeline_builder(self, embodiment: object) -> Callable | None:
        return None
