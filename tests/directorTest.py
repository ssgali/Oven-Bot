import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8")

from pydantic import ValidationError  # noqa: E402

from agent.director.schema import VideoScript, affectedFrameRange, diffScript, resolveScope  # noqa: E402
from e2eTest import check, step  # noqa: E402


def camKf(frame, azimuth=0.0):
    return {"frame": frame, "azimuth": azimuth, "elevation": 12.0, "lens": 85.0, "padding": 1.6}


def shot(id, start, end, azimuth=0.0, preset="soft", overlays=(), transitionIn="cut", transitionInFrames=0):
    return {"id": id, "startFrame": start, "endFrame": end,
            "cameraKeyframes": [camKf(start, azimuth), camKf(end, azimuth)],
            "lightingKeyframes": [{"frame": start, "preset": preset}],
            "textOverlays": list(overlays), "transitionIn": transitionIn, "transitionInFrames": transitionInFrames}


def threeShotScript():
    # totalFrames is a frame COUNT: the last shot's endFrame (90) must be totalFrames - 1, i.e. 91.
    return {"fps": 30, "totalFrames": 91, "objName": "Product",
            "shots": [shot("shot-1", 0, 30), shot("shot-2", 30, 60, azimuth=45), shot("shot-3", 60, 90, azimuth=90)]}


def validationCases():
    VideoScript.model_validate(threeShotScript())  # baseline must be valid

    bad = threeShotScript()
    bad["totalFrames"] = 89
    try:
        VideoScript.model_validate(bad)
        check(False, "totalFrames mismatch should raise")
    except ValidationError:
        pass

    bad = threeShotScript()
    bad["shots"][1]["startFrame"] = 31  # gap between shot-1 and shot-2
    try:
        VideoScript.model_validate(bad)
        check(False, "non-contiguous cut shots should raise")
    except ValidationError:
        pass

    bad = threeShotScript()
    bad["shots"][0]["cameraKeyframes"][0]["frame"] = -1  # outside [0, 30]
    try:
        VideoScript.model_validate(bad)
        check(False, "out-of-range keyframe should raise")
    except ValidationError:
        pass

    bad = threeShotScript()
    bad["shots"][1]["id"] = "shot-1"
    try:
        VideoScript.model_validate(bad)
        check(False, "duplicate shot ids should raise")
    except ValidationError:
        pass

    good = threeShotScript()
    good["shots"][1]["transitionIn"] = "crossfade"
    good["shots"][1]["transitionInFrames"] = 5
    good["shots"][1]["startFrame"] = 25  # overlaps the previous shot by exactly transitionInFrames
    VideoScript.model_validate(good)  # a correctly-declared crossfade overlap is valid

    bad = threeShotScript()
    bad["shots"][1]["transitionIn"] = "crossfade"
    bad["shots"][1]["transitionInFrames"] = 5
    bad["shots"][1]["startFrame"] = 28  # overlap (2) does not match transitionInFrames (5)
    try:
        VideoScript.model_validate(bad)
        check(False, "crossfade overlap must equal transitionInFrames")
    except ValidationError:
        pass


def diffCases():
    old = VideoScript.model_validate(threeShotScript())
    newer = threeShotScript()
    newer["shots"][1]["cameraKeyframes"][1]["azimuth"] = 60.0  # only shot-2 actually changes
    newer = VideoScript.model_validate(newer)
    changed = diffScript(old, newer)
    check(changed == {"shot-2"}, f"diff should isolate the one edited shot: {changed}")

    unchanged = VideoScript.model_validate(threeShotScript())
    check(diffScript(old, unchanged) == set(), "identical scripts should diff to nothing")


def scopeCases():
    script = VideoScript.model_validate(threeShotScript())

    scope, frameRange = resolveScope(script, {"shot-2"}, "scoped")
    check(scope == "scoped" and frameRange == (30, 60), f"single shot should stay scoped: {scope} {frameRange}")

    scope, frameRange = resolveScope(script, {"shot-1", "shot-2"}, "scoped")
    check(scope == "global", f"2/3 shots (>60%) should force global regardless of the model's claim: {scope}")

    scope, frameRange = resolveScope(script, {"shot-1"}, "global")
    check(scope == "global" and frameRange == (0, 90), f"model-declared global should be honored: {scope}")

    withFade = threeShotScript()
    withFade["shots"][1]["transitionIn"] = "crossfade"
    withFade["shots"][1]["transitionInFrames"] = 5
    withFade["shots"][1]["startFrame"] = 25
    withFade = VideoScript.model_validate(withFade)
    frameRange = affectedFrameRange(withFade, {"shot-1"})
    check(frameRange == (0, 35), f"a shot before a crossfade must widen into the overlap: {frameRange}")


def main():
    step("script schema validation", validationCases)
    step("diffScript isolates changed shots", diffCases)
    step("resolveScope guardrail (never trust the model to under-render)", scopeCases)
    print("all director checks passed")


if __name__ == "__main__":
    main()
