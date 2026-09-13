from pathlib import Path

from ..client import BlenderError

viewCode = """
import bpy
for area in bpy.context.screen.areas:
    if area.type != 'VIEW_3D':
        continue
    space = area.spaces.active
    region = next(r for r in area.regions if r.type == 'WINDOW')
    space.shading.type = {shading!r}
    if {shading!r} == 'MATERIAL':
        space.shading.use_scene_lights = True
        space.shading.use_scene_world = True
    space.overlay.show_overlays = {overlays}
    if {cameraView} and bpy.context.scene.camera:
        space.region_3d.view_perspective = 'CAMERA'
        with bpy.context.temp_override(area=area, region=region):
            bpy.ops.view3d.view_center_camera()
    space.region_3d.update()
    area.tag_redraw()
    break
try:
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
except Exception:
    pass
"""


def viewportScreenshot(client, outPath, maxSize=1000, cameraView=True, shading="MATERIAL", overlays=False):
    outPath = Path(outPath).resolve()
    outPath.parent.mkdir(parents=True, exist_ok=True)
    outPath.unlink(missing_ok=True)
    client.execCode(viewCode.format(shading=shading or "SOLID", cameraView=bool(cameraView), overlays=bool(overlays)))
    r = client.send("get_viewport_screenshot", {"max_size": maxSize, "filepath": str(outPath), "format": "png"}, timeout=60)
    if not outPath.is_file():
        raise BlenderError(f"screenshot not written to {outPath}")
    size = outPath.stat().st_size
    return {"path": str(outPath), "width": r["width"], "height": r["height"], "bytes": size,
            "method": r.get("method"), "suspectBlank": size < 5000}
