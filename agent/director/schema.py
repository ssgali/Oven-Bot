from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

Easing = Literal["linear", "easeIn", "easeOut", "easeInOut"]
LightingPreset = Literal["soft", "dramatic", "highKey"]  # studioSetup.py's lightPresets keys
OverlayPosition = Literal["top", "center", "bottom", "lowerThird"]
Scope = Literal["scoped", "global"]
globalFraction = 0.6  # affected shots beyond this share of the timeline force a global rerender


class CameraKeyframe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame: int
    azimuth: float
    elevation: float
    rotationZ: float = 0.0
    lens: float = 85.0
    padding: float = 1.6
    easing: Easing = "easeInOut"  # interpolation into this keyframe from the previous one


class LightingKeyframe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frame: int
    preset: LightingPreset  # hard cut only; no cross-fade between light rigs


class TextOverlay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    content: str
    inFrame: int
    outFrame: int
    position: OverlayPosition = "lowerThird"

    @model_validator(mode="after")
    def ordered(self):
        if self.outFrame <= self.inFrame:
            raise ValueError(f"overlay {self.id}: outFrame must be after inFrame")
        return self


class Shot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str  # stable id: referenced by diffScript and scoped rerender
    startFrame: int
    endFrame: int
    cameraKeyframes: list[CameraKeyframe]
    lightingKeyframes: list[LightingKeyframe]
    textOverlays: list[TextOverlay] = []
    # "crossfade" is modeled for forward-compat (e.g. a future authoring UI) and validated below, but the
    # v1 Blender renderer has one continuous camera timeline and cannot hold two shots' camera paths at
    # the same frame, so it cannot actually dissolve between them; scriptPrompt only ever asks the model
    # for "cut", and affectedFrameRange below still widens conservatively around any crossfade it does see.
    transitionIn: Literal["cut", "crossfade"] = "cut"
    transitionInFrames: int = 0

    @model_validator(mode="after")
    def populated(self):
        if self.endFrame <= self.startFrame:
            raise ValueError(f"shot {self.id}: endFrame must be after startFrame")
        if not self.cameraKeyframes or not self.lightingKeyframes:
            raise ValueError(f"shot {self.id}: needs at least one camera and one lighting keyframe")
        span = (self.startFrame, self.endFrame)
        for kind, kfs in (("camera", self.cameraKeyframes), ("lighting", self.lightingKeyframes)):
            for kf in kfs:
                if not span[0] <= kf.frame <= span[1]:
                    raise ValueError(f"shot {self.id}: {kind} keyframe at {kf.frame} outside [{span[0]}, {span[1]}]")
        for o in self.textOverlays:
            if not (span[0] <= o.inFrame and o.outFrame <= span[1]):
                raise ValueError(f"shot {self.id}: overlay {o.id} outside [{span[0]}, {span[1]}]")
        if self.transitionIn == "crossfade" and self.transitionInFrames <= 0:
            raise ValueError(f"shot {self.id}: crossfade needs transitionInFrames > 0")
        return self


class VideoScript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fps: int = 30
    totalFrames: int
    aspect: Literal["1:1", "4:5", "9:16", "16:9"] = "9:16"
    longEdge: int = 1080
    objName: str = ""  # filled in by the pipeline, not the model
    shots: list[Shot]

    @model_validator(mode="after")
    def deterministic(self):
        if not self.shots:
            raise ValueError("script needs at least one shot")
        shots = sorted(self.shots, key=lambda s: s.startFrame)
        if shots != self.shots:
            raise ValueError("shots must be listed in timeline order")
        if shots[0].startFrame != 0:
            raise ValueError("first shot must start at frame 0")
        for prev, cur in zip(shots, shots[1:]):
            gap = cur.startFrame - prev.endFrame
            overlap = -gap
            if cur.transitionIn == "crossfade":
                if overlap != cur.transitionInFrames:
                    raise ValueError(f"shot {cur.id}: crossfade overlap must equal transitionInFrames "
                                     f"({overlap} != {cur.transitionInFrames})")
            elif gap != 0:
                raise ValueError(f"shot {cur.id}: cut shots must be contiguous with the previous shot (gap {gap})")
        if shots[-1].endFrame != self.totalFrames - 1:
            raise ValueError(f"totalFrames ({self.totalFrames}) is a frame COUNT: the last shot's endFrame "
                             f"must be totalFrames - 1 ({self.totalFrames - 1}), got {shots[-1].endFrame}")
        ids = [s.id for s in shots]
        if len(set(ids)) != len(ids):
            raise ValueError(f"duplicate shot ids: {ids}")
        return self

    def shotIds(self):
        return [s.id for s in self.shots]

    def shotById(self, shotId):
        return next(s for s in self.shots if s.id == shotId)


def diffScript(old, new):
    """Shot ids whose content actually changed between two scripts (by id; added/removed shots count too)."""
    oldById = {s.id: s for s in old.shots}
    newById = {s.id: s for s in new.shots}
    changed = set(oldById) ^ set(newById)
    changed |= {sid for sid in oldById.keys() & newById.keys() if oldById[sid] != newById[sid]}
    return changed


def affectedFrameRange(script, shotIds):
    """[start, end] spanning the given shots, widened by any neighbor's crossfade overlap into that span."""
    shots = script.shots
    idx = {s.id: i for i, s in enumerate(shots)}
    positions = sorted(idx[sid] for sid in shotIds if sid in idx)
    if not positions:
        return None
    start = shots[positions[0]].startFrame
    end = shots[positions[-1]].endFrame
    lastIdx = len(shots) - 1
    if positions[0] > 0 and shots[positions[0]].transitionIn == "crossfade":
        start -= shots[positions[0]].transitionInFrames
    if positions[-1] < lastIdx and shots[positions[-1] + 1].transitionIn == "crossfade":
        end += shots[positions[-1] + 1].transitionInFrames
    return max(0, start), min(script.totalFrames - 1, end)


def resolveScope(script, declaredShotIds, declaredScope):
    """The model proposes a scope; code never trusts it to under-render (mirrors judge.applyPolicy)."""
    actual = set(declaredShotIds)
    total = len(script.shots)
    forceGlobal = declaredScope == "global" or (total and len(actual) / total > globalFraction)
    if forceGlobal:
        return "global", (0, script.totalFrames - 1)
    frameRange = affectedFrameRange(script, actual)
    return "scoped", frameRange
