"""Imports a .glb into the live scene and makes sure it ends up as a single named root object,
since the rest of the pipeline (studioSetup.placeProduct/bounds, clearOld) addresses the product by
one object name and recurses into `children_recursive` for everything else.

This model endpoint's GLBs come out lying flat (thin axis vertical) instead of standing up, and the
glTF importer leaves the root in QUATERNION rotation mode, which silently no-ops every rotation_euler
write the rest of the pipeline does (placeProduct's rotationZ spin, animateShots' per-keyframe spin) —
so both the mode switch and the stand-up correction are mandatory here, not cosmetic."""

import math

import bpy


def main(a):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=a["path"])
    imported = [o for o in bpy.data.objects if o not in before]
    if not imported:
        raise RuntimeError("glTF import produced no objects")

    roots = [o for o in imported if o.parent is None]
    if len(roots) == 1:
        target = roots[0]
    else:
        target = bpy.data.objects.new(a["name"], None)
        bpy.context.scene.collection.objects.link(target)
        for o in roots:
            o.parent = target
    target.name = a["name"]

    target.rotation_mode = "XYZ"  # must be set before writing rotation_euler, see module docstring
    target.rotation_euler.x += math.radians(90)  # this endpoint's GLBs land lying flat; stand them up
    return {"name": target.name, "imported": [o.name for o in imported]}
