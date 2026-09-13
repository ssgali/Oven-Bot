import math

import bmesh
import bpy
from mathutils import Vector

tagKey = "ovenStudio"
defaultNames = {"Cube", "Light", "Camera"}

# (role, azimuth offset from camera, elevation, watts at 1m product, size factor)
lightPresets = {
    "soft": {"world": 0.05, "lights": [("Key", 45, 35, 500, 1.2), ("Fill", -60, 20, 100, 3.0), ("Rim", 160, 45, 300, 1.5)]},
    "dramatic": {"world": 0.02, "lights": [("Key", 60, 40, 800, 1.0), ("Fill", -70, 15, 40, 2.0), ("Rim", 170, 50, 700, 0.8)]},
    "highKey": {"world": 0.5, "lights": [("Key", 30, 30, 500, 4.0), ("Fill", -45, 25, 350, 4.0), ("Rim", 180, 40, 250, 2.5)]},
}


def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    obj[tagKey] = True
    return obj


def ensureNodes(idb):
    if idb.node_tree is None:
        idb.use_nodes = True
    return idb.node_tree


def findNode(nt, nodeType, bl):
    return next((n for n in nt.nodes if n.type == nodeType), None) or nt.nodes.new(bl)


def direction(azimuth, elevation):
    az, el = math.radians(azimuth), math.radians(elevation)
    return Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))


def aim(obj, target):
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def clearOld(productName, clearScene):
    pools = {"MESH": bpy.data.meshes, "LIGHT": bpy.data.lights, "CAMERA": bpy.data.cameras}
    for o in list(bpy.data.objects):
        if o.name == productName or not (o.get(tagKey) or (clearScene and o.name in defaultNames)):
            continue
        data, pool = o.data, pools.get(o.type)
        bpy.data.objects.remove(o, do_unlink=True)
        if pool is not None and data is not None and data.users == 0:
            pool.remove(data)


def bounds(obj):
    bpy.context.view_layer.update()
    pts = [o.matrix_world @ Vector(c) for o in (obj, *obj.children_recursive) if o.type == "MESH" for c in o.bound_box]
    if not pts:
        raise RuntimeError(f"{obj.name} has no mesh geometry")
    return Vector([min(p[i] for p in pts) for i in range(3)]), Vector([max(p[i] for p in pts) for i in range(3)])


def placeProduct(obj, targetSize, rotationZ):
    if "ovenBaseRotZ" not in obj:
        obj["ovenBaseRotZ"] = obj.rotation_euler.z
    obj.rotation_euler.z = obj["ovenBaseRotZ"] + math.radians(rotationZ)
    lo, hi = bounds(obj)
    obj.scale = obj.scale * (targetSize / max(hi - lo))
    lo, hi = bounds(obj)
    obj.location += Vector((-(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2, -lo.z))


def makeMaterial(name, color, roughness):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    nt = ensureNodes(mat)
    bsdf = findNode(nt, "BSDF_PRINCIPLED", "ShaderNodeBsdfPrincipled")
    out = findNode(nt, "OUTPUT_MATERIAL", "ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs[0], out.inputs[0])
    bsdf.inputs["Base Color"].default_value = (*color, 1)
    bsdf.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = (*color, 1)
    return mat


def makeBackdrop(s, color, azimuth):
    width, depth, radius, height, wallY = 16 * s, 10 * s, 2 * s, 8 * s, 3 * s
    profile = [(-depth, 0.0)]
    for i in range(17):
        a = math.pi / 2 * i / 16
        profile.append((wallY - radius + radius * math.sin(a), radius - radius * math.cos(a)))
    profile.append((wallY, height))
    bm = bmesh.new()
    rows = [[bm.verts.new((x, y, z)) for y, z in profile] for x in (-width / 2, width / 2)]
    for i in range(len(profile) - 1):
        bm.faces.new((rows[0][i], rows[1][i], rows[1][i + 1], rows[0][i + 1]))
    mesh = bpy.data.meshes.new("ovenBackdrop")
    bm.to_mesh(mesh)
    bm.free()
    for p in mesh.polygons:
        p.use_smooth = True
    mesh.materials.append(makeMaterial("ovenBackdrop", color, 0.9))
    obj = link(bpy.data.objects.new("ovenBackdrop", mesh))
    obj.rotation_euler.z = math.radians(azimuth)
    return obj


def fitDistance(center, lo, hi, azimuth, elevation, lens, padding, resolution):
    """Direction (product -> camera) and distance so the bounds fit `padding` into frame at `lens`/`resolution`.
    Pure trig, no bpy state: shared by the single-pose studio setup and per-keyframe video camera moves."""
    elevation = max(-80.0, min(80.0, elevation))
    d = direction(azimuth, elevation)
    f = -d
    r = f.cross(Vector((0, 0, 1))).normalized()
    u = r.cross(f)
    resX, resY = resolution
    tanLong = 18 / lens
    tanX, tanY = (tanLong, tanLong * resY / resX) if resX >= resY else (tanLong * resX / resY, tanLong)
    dist = 0.0
    for c in (Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)):
        v = c - center
        z = v.dot(f)
        dist = max(dist, abs(v.dot(r)) * padding / tanX - z, abs(v.dot(u)) * padding / tanY - z)
    return d, dist


def makeCamera(center, lo, hi, a, resolution):
    d, dist = fitDistance(center, lo, hi, a["azimuth"], a["elevation"], a["lens"], a["padding"], resolution)
    data = bpy.data.cameras.new("ovenCamera")
    data.lens, data.sensor_width, data.sensor_fit = a["lens"], 36, "AUTO"
    data.clip_start, data.clip_end = dist * 0.01, dist * 50
    cam = link(bpy.data.objects.new("ovenCamera", data))
    cam.location = center + d * dist
    aim(cam, center)
    bpy.context.scene.camera = cam
    return cam, dist


def makeLights(center, s, preset, azimuth):
    lights = []
    for role, azOff, el, watts, sizeFactor in preset["lights"]:
        data = bpy.data.lights.new(f"oven{role}", "AREA")
        data.energy, data.size = watts * s * s, sizeFactor * s
        obj = link(bpy.data.objects.new(f"oven{role}", data))
        obj.location = center + direction(azimuth + azOff, el) * 3.5 * s
        aim(obj, center)
        lights.append(obj)
    return lights


def setWorld(strength):
    scene = bpy.context.scene
    scene.world = scene.world or bpy.data.worlds.new("ovenWorld")
    nt = ensureNodes(scene.world)
    bg = findNode(nt, "BACKGROUND", "ShaderNodeBackground")
    out = findNode(nt, "OUTPUT_WORLD", "ShaderNodeOutputWorld")
    nt.links.new(bg.outputs[0], out.inputs[0])
    for l in list(bg.inputs["Color"].links):
        nt.links.remove(l)
    bg.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1)
    bg.inputs["Strength"].default_value = strength


def main(a):
    scene = bpy.context.scene
    obj = bpy.data.objects.get(a["objName"])
    if obj is None:
        raise RuntimeError(f"object {a['objName']!r} not in scene")
    clearOld(obj.name, a["clearScene"])
    s = a["targetSize"]
    placeProduct(obj, s, a["rotationZ"])
    lo, hi = bounds(obj)
    center = (lo + hi) / 2
    scene.render.resolution_x, scene.render.resolution_y = a["resolution"]
    scene.render.resolution_percentage = 100
    try:
        scene.view_settings.view_transform = "AgX"
    except TypeError:
        pass
    preset = lightPresets[a["lighting"]]
    backdrop = makeBackdrop(s, a["bgColor"], a["azimuth"])
    cam, dist = makeCamera(center, lo, hi, a, a["resolution"])
    lights = makeLights(center, s, preset, a["azimuth"])
    setWorld(preset["world"])
    rnd = lambda v: [round(x, 4) for x in v]
    return {
        "product": obj.name,
        "bounds": [rnd(lo), rnd(hi)],
        "camera": {"name": cam.name, "location": rnd(cam.location), "distance": round(dist, 4), "lens": a["lens"]},
        "resolution": a["resolution"],
        "created": [o.name for o in (backdrop, cam, *lights)],
    }
