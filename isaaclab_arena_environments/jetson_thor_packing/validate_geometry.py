# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Check exported collision panels for packing clearance; run with container Python."""

import json
import numpy as np
from pathlib import Path

from pxr import Usd, UsdGeom, UsdPhysics

DIRECTORY = Path(__file__).resolve().parents[2] / "artifacts/jetson_thor_packing/assets"
REST_POSES_C = {
    "ac_cable_us": [-0.144, 0.0, 0.0052],
    "ac_cable_eu": [-0.097, 0.0, 0.0052],
    "usb_cable": [-0.021, -0.049, 0.005],
    "power_supply": [0.099, 0.0, 0.006],
    "board_tray": [0.0, 0.0, 0.082],
    "thor_board": [0.0, 0.0, 0.087],
}


def panels(stage, t_W_offset):
    cache = UsdGeom.BBoxCache(0, ["default", "render"], useExtentsHint=False, ignoreVisibility=True)
    result = []
    for prim in stage.Traverse():
        if prim.HasAPI(UsdPhysics.CollisionAPI):
            bounds_W = cache.ComputeWorldBound(prim).ComputeAlignedRange()
            result.append((
                str(prim.GetPath()),
                np.asarray(bounds_W.GetMin()) + t_W_offset,
                np.asarray(bounds_W.GetMax()) + t_W_offset,
            ))
    assert result, "No collision panels found"
    return result


def main():
    stages = {name: Usd.Stage.Open(str(DIRECTORY / f"{name}.physics.usda")) for name in ["background", *REST_POSES_C]}
    collision_boxes = {"background": panels(stages["background"], np.zeros(3))}
    for name, t_C in REST_POSES_C.items():
        collision_boxes[name] = panels(stages[name], np.asarray(t_C) + [0.12, 0.11, 0.75])
    overlaps = []
    names = list(collision_boxes)
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            for a, low_a, high_a in collision_boxes[first]:
                for b, low_b, high_b in collision_boxes[second]:
                    depth = np.minimum(high_a, high_b) - np.maximum(low_a, low_b)
                    if np.all(depth > 1e-5):
                        overlaps.append({"first": first + a, "second": second + b, "penetration_m": depth.tolist()})
    # This deliberately tests independent bodies, excluding intersecting panels within an assembly.
    assert not overlaps, f"Packing layout intersects solid collision panels: {overlaps}"
    cache = UsdGeom.BBoxCache(0, ["default", "render"], useExtentsHint=False, ignoreVisibility=True)
    board_bounds = cache.ComputeWorldBound(stages["thor_board"].GetDefaultPrim()).ComputeAlignedRange()
    board_size = np.asarray(board_bounds.GetSize())
    assert np.allclose(board_size, [0.24319, 0.1124, 0.05688], atol=0.0001)
    report = {
        "success": True,
        "units": "metres",
        "board_exported_size": board_size.tolist(),
        "collision_panel_counts": {name: len(boxes) for name, boxes in collision_boxes.items()},
        "interpenetrating_body_pairs": overlaps,
        "rest_poses_in_carton": REST_POSES_C,
        "tray_clearance_per_side": [0.004, 0.004],
        "board_clearance_per_side": ((np.asarray([0.257, 0.126]) - board_size[:2]) / 2).tolist(),
        "method": "Exported collider AABBs at designed upright resting poses; 10 micrometre overlap tolerance.",
    }
    (DIRECTORY.parent / "geometry_validation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
