# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Require a new placement after the corresponding sequential subtask becomes active."""

from dataclasses import replace

from isaaclab_arena.assets.register import register_task
from isaaclab_arena.tasks.object_in_task import ObjectInTask
from isaaclab_arena.tasks.predicates.spatial import object_in_target_aabb


@register_task
class EnterHousingTask(ObjectInTask):
    """Observe the object outside its housing before accepting ObjectInTask's settled placement.

    Sequential progress enables this first predicate only after the preceding subtask.
    An already loaded tray therefore cannot silently satisfy a later board-placement step.
    Contact sensing, containment, settling, and the current final condition remain inherited.
    """

    def _outside(self, env):
        return ~object_in_target_aabb(env, self.object.name, self.target.name, self.minimum_contained_fraction)

    def get_termination_cfg(self):
        cfg = super().get_termination_cfg()
        cfg.success = [
            replace(criterion, name="enter_housing", predicate_sequence=[self._outside, *criterion.predicate_sequence])
            for criterion in cfg.success
        ]
        return cfg
