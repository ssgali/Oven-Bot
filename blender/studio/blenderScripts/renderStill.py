import time

import bpy


def setEevee(scene):
    for engine in ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"):
        try:
            scene.render.engine = engine
            return engine
        except TypeError:
            pass
    raise RuntimeError("EEVEE engine not available")


def enableGpu(scene):
    addon = bpy.context.preferences.addons.get("cycles")
    if addon is None:
        return "CPU"
    prefs = addon.preferences
    for kind in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        devices = [d for d in prefs.devices if d.type == kind]
        if devices:
            for d in devices:
                d.use = True
            scene.cycles.device = "GPU"
            return kind
    scene.cycles.device = "CPU"
    return "CPU"


def isolateProduct(scene, cycles):
    # film_transparent only clears the world; the backdrop mesh would still fill the frame
    backdrop = next((o for o in scene.objects if o.get("ovenStudio") and o.name.startswith("ovenBackdrop")), None)
    if backdrop is None:
        return lambda: None
    old = (backdrop.hide_render, backdrop.is_shadow_catcher)
    if cycles:
        backdrop.is_shadow_catcher = True
    else:
        backdrop.hide_render = True

    def restore():
        backdrop.hide_render, backdrop.is_shadow_catcher = old

    return restore


def main(a):
    scene = bpy.context.scene
    if scene.camera is None:
        raise RuntimeError("scene has no camera; run setupStudio first")
    restore = isolateProduct(scene, a["engine"] == "cycles") if a["transparent"] else (lambda: None)
    if a["engine"] == "cycles":
        scene.render.engine = "CYCLES"
        scene.cycles.samples = a["samples"] or 128
        scene.cycles.use_denoising = True
        device = enableGpu(scene)
    else:
        setEevee(scene)
        scene.eevee.taa_render_samples = a["samples"] or 64
        device = "GPU"
    r = scene.render
    r.film_transparent = a["transparent"]
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA" if a["transparent"] else "RGB"
    r.filepath = a["outPath"]
    t = time.perf_counter()
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        restore()
    return {
        "outPath": a["outPath"],
        "seconds": round(time.perf_counter() - t, 2),
        "resolution": [r.resolution_x, r.resolution_y],
        "engine": r.engine,
        "device": device,
    }
