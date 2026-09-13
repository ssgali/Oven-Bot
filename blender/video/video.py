from pathlib import Path

from ..client import BlenderError
from ..studio.studio import aspects, lightingPresets, resolutionFor  # noqa: F401 (re-exported)

scriptsDir = Path(__file__).parent / "blenderScripts"
studioScriptsDir = Path(__file__).parents[1] / "studio" / "blenderScripts"


def animateShots(client, script, targetSize=1.0, bgColor=(0.8, 0.78, 0.75), timeout=180):
    """Builds the studio and keyframes camera/product/lighting for the whole timeline from a VideoScript dict.
    `script` must already have `objName` filled in."""
    resolution = resolutionFor(script["aspect"], script["longEdge"])
    args = {"objName": script["objName"], "studioScriptsDir": str(studioScriptsDir), "script": script,
            "targetSize": targetSize, "bgColor": list(bgColor), "resolution": resolution}
    return client.runScript(scriptsDir / "animateShots.py", args, timeout=timeout)


def renderRange(client, outDir, startFrame, endFrame, engine="eevee", samples=None, transparent=False,
                timeout=1800):
    if engine not in ("eevee", "cycles"):
        raise ValueError("engine must be 'eevee' or 'cycles'")
    outDir = Path(outDir).resolve()
    outDir.mkdir(parents=True, exist_ok=True)
    args = {"studioScriptsDir": str(studioScriptsDir), "outDir": str(outDir), "startFrame": startFrame,
            "endFrame": endFrame, "engine": engine, "samples": samples, "transparent": transparent}
    r = client.runScript(scriptsDir / "renderRange.py", args, timeout=timeout)
    missing = [f for f in r["frames"] if not Path(f).is_file()]
    if missing:
        raise BlenderError(f"render finished but {len(missing)} frame(s) were not written, e.g. {missing[0]}")
    return r
