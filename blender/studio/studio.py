from pathlib import Path

from ..client import BlenderError

scriptsDir = Path(__file__).parent / "blenderScripts"
aspects = {"1:1": (1, 1), "4:5": (4, 5), "9:16": (9, 16), "16:9": (16, 9)}
lightingPresets = ("soft", "dramatic", "highKey")


def resolutionFor(aspect, longEdge):
    if aspect not in aspects:
        raise ValueError(f"aspect must be one of {list(aspects)}")
    w, h = aspects[aspect]
    return [longEdge, round(longEdge * h / w)] if w >= h else [round(longEdge * w / h), longEdge]


def setupStudio(client, objName, clearScene=True, targetSize=1.0, rotationZ=0.0, bgColor=(0.8, 0.78, 0.75),
                lighting="soft", azimuth=25.0, elevation=12.0, lens=85.0, padding=1.6, aspect="1:1", longEdge=1080):
    if lighting not in lightingPresets:
        raise ValueError(f"lighting must be one of {lightingPresets}")
    args = {
        "objName": objName, "clearScene": clearScene, "targetSize": targetSize, "rotationZ": rotationZ,
        "bgColor": list(bgColor), "lighting": lighting, "azimuth": azimuth, "elevation": elevation,
        "lens": lens, "padding": padding, "resolution": resolutionFor(aspect, longEdge),
    }
    return client.runScript(scriptsDir / "studioSetup.py", args, timeout=120)


def renderStill(client, outPath, engine="eevee", samples=None, transparent=False, timeout=900):
    if engine not in ("eevee", "cycles"):
        raise ValueError("engine must be 'eevee' or 'cycles'")
    outPath = Path(outPath).resolve()
    outPath.parent.mkdir(parents=True, exist_ok=True)
    outPath.unlink(missing_ok=True)
    args = {"outPath": str(outPath), "engine": engine, "samples": samples, "transparent": transparent}
    r = client.runScript(scriptsDir / "renderStill.py", args, timeout=timeout)
    if not outPath.is_file() or outPath.stat().st_size == 0:
        raise BlenderError(f"render finished but {outPath} was not written")
    return {**r, "bytes": outPath.stat().st_size}
