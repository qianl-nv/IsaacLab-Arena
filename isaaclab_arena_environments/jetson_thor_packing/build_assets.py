# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Run in Blender through MCP; export metre-scale Thor kit and compartmented packaging."""

import bpy
import json
import math
from pathlib import Path

from mathutils import Vector

OUTPUT = Path(globals().get("OUTPUT", "/tmp/jetson_thor_assets"))
OUTPUT.mkdir(parents=True, exist_ok=True)


def material(name, color, metallic=0.0, roughness=0.6):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    shader = mat.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    return mat


def root(name):
    obj = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(obj)
    return obj


def box(parent, name, t_P, size, mat, bevel=0, collision=True):
    bpy.ops.mesh.primitive_cube_add(size=1, location=t_P)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.parent = parent
    if mat:
        obj.data.materials.append(mat)
    if bevel:
        modifier = obj.modifiers.new("Soft manufacturing edges", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
        obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
    if collision:
        box(parent, "COL_" + name, t_P, size, None, collision=False).hide_render = True
    return obj


def tube(parent, name, points, radius, mat):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = radius
    curve.bevel_resolution = 3
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, t_P in zip(spline.points, points):
        point.co = (*t_P, 1)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.parent = parent
    obj.data.materials.append(mat)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")
    obj.select_set(False)
    return obj


def label(parent, name, text, t_P, size, mat, rotation=(0, 0, 0)):
    curve = bpy.data.curves.new(name, "FONT")
    curve.body = text
    curve.size = size
    curve.extrude = 0.000015
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.parent = parent
    obj.location = t_P
    obj.rotation_euler = rotation
    obj.data.materials.append(mat)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.convert(target="MESH")
    obj.select_set(False)


def coil(parent, name, center, radii, radius, turns, mat):
    points = []
    for i in range(turns * 96 + 1):
        theta = 2 * math.pi * i / 96
        points.append((
            center[0] + radii[0] * math.cos(theta),
            center[1] + radii[1] * math.sin(theta),
            center[2] + i / 96 * radius * 1.9,
        ))
    tube(parent, name, points, radius, mat)
    # A coiled lead is one rigid bundle, with a single conservative collision envelope.
    box(
        parent,
        "COL_" + name,
        (center[0], center[1], center[2] + turns * radius * 0.95),
        (2 * (radii[0] + radius), 2 * (radii[1] + radius), (turns * 1.9 + 2) * radius),
        None,
        collision=False,
    ).hide_render = True


def export_asset(obj, filename):
    bpy.ops.object.select_all(action="DESELECT")
    for child in [obj, *obj.children_recursive]:
        child.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.wm.usd_export(
        filepath=str(OUTPUT / (filename + ".usdc")),
        selected_objects_only=True,
        evaluation_mode="VIEWPORT",
        export_materials=True,
        generate_preview_surface=True,
        root_prim_path="/Asset",
    )


def build():
    # This script runs in a dedicated Blender scene; preserve any other user scenes.
    for previous in list(bpy.data.scenes):
        if previous.name.startswith("Jetson Thor packing"):
            for obj in list(previous.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.scenes.remove(previous)
    scene = bpy.data.scenes.new("Jetson Thor packing")
    bpy.context.window.scene = scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    kraft = material("Kraft cardboard", (0.48, 0.32, 0.17), roughness=0.95)
    edge = material("Cardboard cut edges", (0.63, 0.46, 0.27), roughness=0.98)
    black = material("Black rubber and polymer", (0.012, 0.016, 0.021), roughness=0.5)
    foam = material("Black protective lining", (0.022, 0.028, 0.035), roughness=0.95)
    silver = material("Brushed aluminium", (0.48, 0.52, 0.56), metallic=0.8, roughness=0.32)
    steel = material("Connector shell", (0.42, 0.45, 0.48), metallic=0.85, roughness=0.25)
    green = material("NVIDIA green", (0.32, 0.65, 0.012), roughness=0.45)
    white = material("White printing", (0.88, 0.9, 0.88), roughness=0.7)
    blue = material("USB insert", (0.018, 0.13, 0.42), roughness=0.6)
    wood = material("Maple work surface", (0.55, 0.36, 0.19), roughness=0.75)
    gray = material("Table frame", (0.08, 0.11, 0.14), metallic=0.4)

    background = root("background")
    table = root("Table")
    table.parent = background
    box(table, "Tabletop", (0, 0, 0.725), (1.35, 0.85, 0.05), wood, 0.005)
    for x in (-0.58, 0.58):
        for y in (-0.33, 0.33):
            box(table, "Leg", (x, y, 0.35), (0.045, 0.045, 0.7), gray, 0.003)
    box(table, "Floor", (0, 0, -0.025), (5, 5, 0.05), gray)

    # Carton frame C has its origin at the exterior bottom. Dimensions in metres.
    carton = root("Carton")
    carton.parent = background
    carton.location = (0.12, 0.11, 0.75)
    box(carton, "Carton_floor", (0, 0, 0.002), (0.36, 0.22, 0.004), kraft)
    for x in (-0.1775, 0.1775):
        box(carton, "Side_wall", (x, 0, 0.082), (0.005, 0.22, 0.156), kraft)
    for y in (-0.1075, 0.1075):
        box(carton, "End_wall", (0, y, 0.082), (0.35, 0.005, 0.156), kraft)
    # Ledges stand 2 mm above the dividers so the carton reliably supports the tray.
    for x in (-0.17, 0.17):
        box(carton, "Tray_ledge", (x, 0, 0.079), (0.01, 0.202, 0.006), edge)
    lid = root("OpenLid")
    lid.parent = background
    lid.location = (0.12, 0.221, 0.91)
    lid.rotation_euler.x = math.radians(78)
    box(lid, "Open_cardboard_lid", (0, 0.107, 0), (0.36, 0.214, 0.004), kraft)
    box(lid, "Product_label", (-0.015, 0.11, 0.0022), (0.22, 0.095, 0.0003), black, collision=False)
    label(lid, "Label", "NVIDIA\nJetson AGX Thor\nDeveloper Kit", (-0.11, 0.145, 0.0025), 0.014, white)
    box(lid, "Green_stripe", (-0.13, 0.11, 0.0023), (0.007, 0.095, 0.0003), green, collision=False)

    # Each target is a separate fixed rigid body, allowing real filtered contact checks.
    ac_bay = root("ACBay")
    ac_bay.parent = background
    ac_bay.location = carton.location
    box(ac_bay, "AC_floor", (-0.1205, 0, 0.005), (0.099, 0.202, 0.002), edge)
    for x in (-0.171, -0.070):
        box(ac_bay, "AC_divider", (x, 0, 0.043), (0.003, 0.202, 0.074), kraft)
    for y in (-0.100, 0.100):
        box(ac_bay, "AC_end", (-0.1205, y, 0.043), (0.099, 0.003, 0.074), kraft)

    usb_bay = root("USBBay")
    usb_bay.parent = background
    usb_bay.location = carton.location
    box(usb_bay, "USB_floor", (-0.021, -0.049, 0.005), (0.092, 0.104, 0.002), edge)
    for x in (-0.0685, 0.0265):
        box(usb_bay, "USB_side", (x, -0.049, 0.043), (0.003, 0.104, 0.074), kraft)
    for y in (-0.100, 0.0045):
        box(usb_bay, "USB_end", (-0.021, y, 0.043), (0.092, 0.003, 0.074), kraft)

    power_bay = root("PowerBay")
    power_bay.parent = background
    power_bay.location = carton.location
    box(power_bay, "Adapter_floor", (0.099, 0, 0.005), (0.139, 0.202, 0.002), foam)
    box(power_bay, "DC_lead_floor", (-0.021, 0.054, 0.005), (0.092, 0.093, 0.002), edge)
    for y in (-0.100, 0.100):
        box(power_bay, "Adapter_end", (0.099, y, 0.043), (0.139, 0.003, 0.074), kraft)
    box(power_bay, "Adapter_side", (0.17, 0, 0.043), (0.003, 0.202, 0.074), kraft)
    box(power_bay, "Lead_back", (-0.021, 0.1, 0.043), (0.092, 0.003, 0.074), kraft)
    box(power_bay, "Lead_side", (-0.0685, 0.054, 0.043), (0.003, 0.093, 0.074), kraft)
    # Divider has an open neck so the adapter's permanently attached DC lead can cross it.
    box(power_bay, "Short_divider", (0.027, -0.05, 0.043), (0.003, 0.1, 0.074), kraft)
    export_asset(background, "background")

    tray = root("board_tray")
    box(tray, "Tray_base", (0, 0, 0.002), (0.342, 0.202, 0.004), kraft)
    box(tray, "Antistatic_liner", (0, 0, 0.0045), (0.255, 0.124, 0.001), foam)
    for x in (-0.14975, 0.14975):
        box(tray, "End_bolster", (x, 0, 0.035), (0.0425, 0.202, 0.062), kraft, 0.001)
    for y in (-0.082, 0.082):
        box(tray, "Side_bolster", (0, y, 0.035), (0.257, 0.038, 0.062), kraft, 0.001)
    label(tray, "Tray_marking", "JETSON AGX THOR", (-0.084, -0.089, 0.0662), 0.009, black)
    export_asset(tray, "board_tray")

    board = root("thor_board")
    # Published overall dimensions include feet and thermal enclosure: 243.19 x 112.40 x 56.88 mm.
    box(board, "Black_base", (0, 0, 0.017), (0.24319, 0.1124, 0.027), black, 0.002)
    box(board, "Aluminium_housing", (0, 0, 0.04269), (0.24319, 0.1124, 0.02638), silver, 0.002)
    for x in (-0.101, 0.101):
        for y in (-0.039, 0.039):
            box(board, "Rubber_foot", (x, y, 0.00175), (0.018, 0.012, 0.0035), black, 0.001)
    box(board, "Cooling_grille", (-0.061, 0, 0.0563), (0.108, 0.102, 0.001), black, 0.0003, collision=False)
    for i in range(46):
        box(
            board,
            "Aluminium_cooling_fin",
            (-0.111 + i * 0.0022, 0, 0.0566),
            (0.00065, 0.093, 0.0005),
            silver,
            collision=False,
        )
    label(board, "Top_brand", "NVIDIA", (0.072, -0.035, 0.0559), 0.009, gray, (0, 0, math.pi / 2))
    label(board, "Top_model", "JETSON AGX THOR", (0.005, -0.044, 0.0559), 0.006, gray)
    # Recessed front I/O, kept within the official outer envelope.
    for x, width, height, insert in [
        (-0.096, 0.014, 0.006, blue),
        (-0.071, 0.014, 0.006, blue),
        (-0.043, 0.009, 0.004, black),
        (-0.025, 0.009, 0.004, black),
        (0.005, 0.016, 0.012, black),
        (0.037, 0.018, 0.007, black),
        (0.069, 0.017, 0.007, black),
    ]:
        box(board, "Port_shell", (x, -0.0558, 0.017), (width + 0.002, 0.0005, height + 0.002), steel, collision=False)
        box(board, "Port_recess", (x, -0.0561, 0.017), (width, 0.00015, height), insert, collision=False)
    box(board, "Power_button", (0.1, -0.0561, 0.017), (0.006, 0.0002, 0.006), green, collision=False)
    export_asset(board, "thor_board")

    ac_roots = []
    for name, european in [("ac_cable_us", False), ("ac_cable_eu", True)]:
        lead = root(name)
        coil(lead, "AC_coil", (0, 0, 0.004), (0.014, 0.068), 0.0032, 3, black)
        box(lead, "Cable_tie", (0, 0, 0.014), (0.039, 0.007, 0.024), black, 0.001)
        box(lead, "Wall_plug", (0, 0.069, 0.023), (0.027, 0.027, 0.025), black, 0.004)
        for x in (-0.007, 0.007):
            box(lead, "Mains_pin", (x, 0.085, 0.023), (0.004, 0.009, 0.004 if european else 0.008), steel, 0.001)
        box(lead, "IEC_C5_connector", (0, -0.069, 0.023), (0.026, 0.028, 0.018), black, 0.005)
        export_asset(lead, name)
        ac_roots.append(lead)

    usb = root("usb_cable")
    coil(usb, "USB_coil", (0, 0, 0.003), (0.029, 0.032), 0.002, 3, black)
    box(usb, "USB_tie", (0, 0, 0.009), (0.065, 0.005, 0.015), black, 0.001)
    box(usb, "USB_A_shell", (-0.014, -0.033, 0.017), (0.013, 0.014, 0.006), steel, 0.001)
    box(usb, "USB_A_tongue", (-0.014, -0.0401, 0.017), (0.009, 0.0002, 0.002), blue, collision=False)
    box(usb, "USB_C_shell", (0.015, 0.034, 0.017), (0.009, 0.012, 0.004), steel, 0.001)
    export_asset(usb, "usb_cable")

    psu = root("power_supply")
    box(psu, "Power_adapter", (0, 0, 0.024), (0.116, 0.148, 0.048), black, 0.006)
    box(psu, "Adapter_label", (0, 0, 0.0481), (0.083, 0.082, 0.0002), gray, collision=False)
    label(psu, "Adapter_text", "NVIDIA\nUSB-C POWER\nAC ADAPTER", (-0.035, 0.018, 0.0483), 0.009, white)
    for x in (-0.006, 0.006):
        box(psu, "C5_socket", (x, -0.0741, 0.025), (0.007, 0.0002, 0.008), steel, 0.002, collision=False)
    coil(psu, "Captive_DC_lead", (-0.12, 0.052, 0.004), (0.031, 0.034), 0.0028, 3, black)
    tube(
        psu,
        "DC_strain_relief",
        [(-0.058, 0.045, 0.023), (-0.075, 0.045, 0.023), (-0.087, 0.052, 0.012), (-0.089, 0.052, 0.004)],
        0.0028,
        black,
    )
    box(psu, "USB_C_power_tip", (-0.12, 0.085, 0.021), (0.011, 0.014, 0.007), steel, 0.002)
    box(psu, "DC_tie", (-0.12, 0.052, 0.013), (0.069, 0.007, 0.024), black, 0.001)
    export_asset(psu, "power_supply")

    # Save a useful, scattered tabletop layout in Blender as well as independent USDs.
    layout = {
        "thor_board": (-0.39, -0.17, 0.752),
        "board_tray": (-0.39, 0.16, 0.752),
        "ac_cable_us": (-0.10, -0.23, 0.752),
        "ac_cable_eu": (0.005, -0.22, 0.752),
        "usb_cable": (0.16, -0.24, 0.752),
        "power_supply": (0.46, -0.14, 0.752),
    }
    for obj in [board, tray, *ac_roots, usb, psu]:
        obj.location = layout[obj.name]
    for obj in scene.objects:
        if obj.name.startswith("COL_"):
            obj.hide_set(True)
    bpy.ops.object.camera_add(location=(1.05, -1.30, 1.65))
    scene.camera = bpy.context.object
    scene.camera.rotation_euler = (Vector((0, 0, 0.8)) - scene.camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera.data.type = "ORTHO"
    scene.camera.data.ortho_scale = 1.5
    for t_W, energy, size in [((0, -0.6, 2.5), 450, 2), ((-1, 1, 2), 300, 1.5)]:
        bpy.ops.object.light_add(type="AREA", location=t_W)
        bpy.context.object.data.energy = energy
        bpy.context.object.data.shape = "DISK"
        bpy.context.object.data.size = size
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1000
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(OUTPUT / "blender_scene.png")
    bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT / "jetson_thor_packing.blend"))
    bpy.ops.render.render(write_still=True)
    (OUTPUT / "dimensions.json").write_text(
        json.dumps(
            {
                "units": "metres",
                "board": [0.24319, 0.1124, 0.05688],
                "carton_external": [0.36, 0.22, 0.16],
                "tray_external": [0.342, 0.202, 0.066],
                "board_well": [0.257, 0.126, 0.061],
                "tray_floor_bottom_in_carton": 0.082,
                "dimension_sources": {
                    "board": "NVIDIA published mechanical dimensions",
                    "packaging_and_accessories": "photo-based estimates with explicit clearances",
                },
                "initial_positions": layout,
            },
            indent=2,
        )
    )
    print("JETSON_ASSETS_EXPORTED", str(OUTPUT))


build()
