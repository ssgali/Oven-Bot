"""Builds the studio once, then keyframes the camera, product spin and lighting rig across the whole
timeline from a VideoScript dict. Text overlays are not handled here — compose/videoOverlay composites
them onto rendered frames in a separate step, so a text-only revision never needs a Blender round-trip.

Reuses studio/blenderScripts/studioSetup.py's trig/rig-building functions via a sys.path shim, since
BlenderClient.runScript() execs each script in isolation with no package context (see video/video.py).

fcurve access (fcurvesOf below) is written against Blender 5.2's layered-action API and was smoke-tested
against a live Blender 5.2.1 instance; an older pre-4.4 Blender would need the flat `action.fcurves` path
instead."""

import math
import sys

import bpy
from mathutils import Vector

easingMap = {"linear": "LINEAR", "easeIn": "SINE", "easeOut": "SINE", "easeInOut": "SINE"}
easingSubMode = {"easeIn": "EASE_IN", "easeOut": "EASE_OUT", "easeInOut": "EASE_IN_OUT"}


def fcurvesOf(animatable):
    """Blender 4.4+ moved fcurves under Action.layers[*].strips[*].channelbags[*] (the old flat
    Action.fcurves is gone); a channelbag only applies to animation_data.action_slot's own datablock,
    which matters once an action is shared, so filter by slot handle. Verified against a live Blender
    5.2 instance in this repo's addon; older Blender versions would need the flat `action.fcurves` path."""
    ad = getattr(animatable, "animation_data", None)
    if not ad or not ad.action or not ad.action_slot:
        return []
    handle = ad.action_slot.handle
    return [fc for layer in ad.action.layers for strip in layer.strips for cb in strip.channelbags
            if cb.slot_handle == handle for fc in cb.fcurves]


def keyframePointAt(fcurve, frame):
    return next((k for k in fcurve.keyframe_points if abs(k.co.x - frame) < 0.5), None)


def setEasing(fcurve, frame, easing):
    kp = keyframePointAt(fcurve, frame)
    if kp is None:
        return
    kp.interpolation = easingMap.get(easing, "BEZIER")
    if easing in easingSubMode:
        kp.easing = easingSubMode[easing]


def setEasingAllFcurves(animatable, frame, easing):
    for fc in fcurvesOf(animatable):
        setEasing(fc, frame, easing)


def constantAllFcurves(animatable, frame):
    for fc in fcurvesOf(animatable):
        kp = keyframePointAt(fc, frame)
        if kp is not None:
            kp.interpolation = "CONSTANT"


def keyframeCamera(ss, cam, center, lo, hi, kf, resolution):
    d, dist = ss.fitDistance(center, lo, hi, kf["azimuth"], kf["elevation"], kf["lens"], kf["padding"], resolution)
    cam.location = center + d * dist
    cam.keyframe_insert("location", frame=kf["frame"])
    ss.aim(cam, center)
    cam.keyframe_insert("rotation_euler", frame=kf["frame"])
    cam.data.lens = kf["lens"]
    cam.data.keyframe_insert("lens", frame=kf["frame"])
    setEasingAllFcurves(cam, kf["frame"], kf["easing"])
    setEasingAllFcurves(cam.data, kf["frame"], kf["easing"])


def keyframeProduct(obj, kf):
    obj.rotation_euler.z = obj["ovenBaseRotZ"] + math.radians(kf["rotationZ"])
    obj.keyframe_insert("rotation_euler", index=2, frame=kf["frame"])
    setEasingAllFcurves(obj, kf["frame"], kf["easing"])


def swapLightingRig(ss, scene, oldRig, preset, azimuth, s, center, frame):
    """Hard cut: fade the old rig out and a new one in at exactly `frame` (CONSTANT interpolation)."""
    for light in oldRig:
        light.hide_render = True
        light.keyframe_insert("hide_render", frame=frame)
        constantAllFcurves(light, frame)
    newRig = ss.makeLights(center, s, preset, azimuth)
    for light in newRig:
        light.hide_render = False
        light.keyframe_insert("hide_render", frame=frame)
        constantAllFcurves(light, frame)
    return newRig


def keyframeWorldStrength(scene, strength, frame):
    nt = scene.world.node_tree
    bg = next(n for n in nt.nodes if n.type == "BACKGROUND")
    bg.inputs["Strength"].default_value = strength
    bg.inputs["Strength"].keyframe_insert("default_value", frame=frame)
    constantAllFcurves(nt, frame)


def main(a):
    sys.path.insert(0, a["studioScriptsDir"])
    import studioSetup as ss  # noqa: E402

    scene = bpy.context.scene
    script = a["script"]
    resolution = a["resolution"]
    s = a.get("targetSize", 1.0)

    obj = bpy.data.objects.get(a["objName"])
    if obj is None:
        raise RuntimeError(f"object {a['objName']!r} not in scene")
    ss.clearOld(obj.name, clearScene=True)

    shots = script["shots"]
    firstCam = shots[0]["cameraKeyframes"][0]
    ss.placeProduct(obj, s, firstCam["rotationZ"])
    lo, hi = ss.bounds(obj)
    center = (lo + hi) / 2

    scene.render.resolution_x, scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.frame_start, scene.frame_end = 0, script["totalFrames"] - 1  # totalFrames is a count, not an index
    try:
        scene.view_settings.view_transform = "AgX"
    except TypeError:
        pass

    backdrop = ss.makeBackdrop(s, a.get("bgColor", (0.8, 0.78, 0.75)), firstCam["azimuth"])
    cam, _ = ss.makeCamera(center, lo, hi, dict(firstCam), resolution)
    ss.setWorld(0.05)  # placeholder; first shot's lighting keyframe below sets the real strength at frame 0

    rig = []
    created = [backdrop, cam]
    for shot in shots:
        for kf in shot["cameraKeyframes"]:
            keyframeCamera(ss, cam, center, lo, hi, kf, resolution)
            keyframeProduct(obj, kf)
        lightKf = shot["lightingKeyframes"][0]  # v1: one hard-cut preset per shot, at the shot's start
        preset = ss.lightPresets[lightKf["preset"]]
        rig = swapLightingRig(ss, scene, rig, preset, shot["cameraKeyframes"][0]["azimuth"], s, center,
                              shot["startFrame"])
        keyframeWorldStrength(scene, preset["world"], shot["startFrame"])
        created += rig

    return {
        "product": obj.name,
        "bounds": [[round(x, 4) for x in lo], [round(x, 4) for x in hi]],
        "totalFrames": script["totalFrames"],
        "resolution": resolution,
        "created": [o.name for o in created],
    }
