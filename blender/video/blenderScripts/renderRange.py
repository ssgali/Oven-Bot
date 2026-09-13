"""Renders an already-keyframed timeline (see animateShots.py) to one PNG per frame over [start, end].
Extends studio/blenderScripts/renderStill.py's single-frame pattern; reuses its engine/transparency setup
via the same sys.path shim animateShots.py uses."""

import sys
import time

import bpy


def main(a):
    sys.path.insert(0, a["studioScriptsDir"])
    from renderStill import configureEngine, isolateProduct  # noqa: E402

    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("scene has no camera; run animateShots first")
    restore = isolateProduct(scene, a["engine"] == "cycles") if a["transparent"] else (lambda: None)
    device = configureEngine(scene, a["engine"], a["samples"], a["transparent"])
    outDir = a["outDir"]
    t = time.perf_counter()
    rendered = []
    try:
        for frame in range(a["startFrame"], a["endFrame"] + 1):
            scene.frame_set(frame)
            path = f"{outDir}/frame_{frame:05d}.png"
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            rendered.append(path)
    finally:
        restore()
    return {
        "startFrame": a["startFrame"], "endFrame": a["endFrame"], "frames": rendered,
        "seconds": round(time.perf_counter() - t, 2),
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "engine": scene.render.engine, "device": device,
    }
