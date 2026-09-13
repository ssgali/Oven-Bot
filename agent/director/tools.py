from langchain_core.tools import tool

from blender.video import animateShots, encodeFrames, renderRange
from compose.videoOverlay import backdropColor, compositeOverlays, framePattern, loadOrComputeAccent

previewFrameName = "preview_{shotId}.png"


def _renderRange(client, jobPaths, script, startFrame, endFrame, imagePath=None, objName=""):
    """Re-applies the current script's keyframes, re-renders [startFrame, endFrame], recomposites
    overlays for that range and re-encodes — the full-cost path, for camera/lighting changes."""
    accent = loadOrComputeAccent(jobPaths.versionDir, imagePath, objName)
    animateShots(client, script, bgColor=backdropColor(accent))
    renderRange(client, jobPaths.rawDir, startFrame, endFrame, jobPaths.engine, jobPaths.samples)
    compositeOverlays(jobPaths.rawDir, script, jobPaths.compositedDir, startFrame, endFrame, accent=accent)
    return encodeFrames(jobPaths.compositedDir, jobPaths.videoPath, script["fps"])


def makeDirectorTools(client, jobPaths, scriptBox, imagePath=None, objName=""):
    """Tools for the revise_script agent loop, closed over the live BlenderClient, this revision's file
    paths, and `scriptBox` — a {"script": ...} holder graph.py swaps in-place once propose_revision commits
    to a new script, so every tool below always acts on the currently-proposed script. `imagePath`/`objName`
    are only a fallback for resolving the job's brand accent color if it hasn't been cached yet (e.g. a job
    from before theme caching existed); the normal path just rereads the cache render() already wrote."""

    @tool
    def get_scene_state() -> dict:
        """Current Blender scene info (objects, camera), for grounding before deciding a fix."""
        return client.sceneInfo()

    @tool
    def render_range(startFrame: int, endFrame: int) -> dict:
        """Re-render this frame range from the current script (camera/lighting), recomposite its text
        overlays and re-encode the video. Use when the fix changes camera moves or lighting."""
        return _renderRange(client, jobPaths, scriptBox["script"], startFrame, endFrame, imagePath, objName)

    @tool
    def render_full() -> dict:
        """Re-render the entire timeline, recomposite and re-encode. Use when the change is global or
        touches most shots."""
        return _renderRange(client, jobPaths, scriptBox["script"], 0, scriptBox["script"]["totalFrames"] - 1,
                            imagePath, objName)

    @tool
    def recomposite_overlays(startFrame: int, endFrame: int) -> dict:
        """Redraw only text overlays for this range from the existing raw renders — no Blender involved.
        Use when the fix is text-only (wording, timing, position); follow with encode_video."""
        accent = loadOrComputeAccent(jobPaths.versionDir, imagePath, objName)
        return compositeOverlays(jobPaths.rawDir, scriptBox["script"], jobPaths.compositedDir, startFrame, endFrame,
                                 accent=accent)

    @tool
    def encode_video() -> dict:
        """Encode the composited frame directory into the final mp4. Call after recomposite_overlays."""
        return encodeFrames(jobPaths.compositedDir, jobPaths.videoPath, scriptBox["script"]["fps"])

    @tool
    def extract_preview_frame(shotId: str) -> str:
        """Path to a composited preview frame at the given shot's midpoint, so you can look at what the
        reviewer saw (or check a fix) before finishing. The image is shown to you on the next turn."""
        script = scriptBox["script"]
        shot = next(s for s in script["shots"] if s["id"] == shotId)
        frame = (shot["startFrame"] + shot["endFrame"]) // 2
        name = framePattern.format(frame)
        composited = jobPaths.compositedDir / name
        if not composited.is_file():
            accent = loadOrComputeAccent(jobPaths.versionDir, imagePath, objName)
            compositeOverlays(jobPaths.rawDir, script, jobPaths.compositedDir, frame, frame, accent=accent)
        return str(composited)

    return [get_scene_state, render_range, render_full, recomposite_overlays, encode_video, extract_preview_frame]
