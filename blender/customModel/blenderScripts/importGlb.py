"""Imports a .glb into the live scene and makes sure it ends up as a single named root object,
since the rest of the pipeline (studioSetup.placeProduct/bounds, clearOld) addresses the product by
one object name and recurses into `children_recursive` for everything else."""

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
    return {"name": target.name, "imported": [o.name for o in imported]}
