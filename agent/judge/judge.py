from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..vlm import VlmError
from .metrics import flattenForViewing, hardGate, imageMetrics
from .prompts import judgePrompt, judgeSystem

Action = Literal["proceed", "retry", "fallback2d"]
Lighting = Literal["soft", "dramatic", "highKey"]
defaultParams = {"azimuth": 25.0, "elevation": 12.0, "rotationZ": 0.0, "lighting": "soft", "padding": 1.6}
ranges = {"azimuth": (-180, 180), "elevation": (-10, 45), "rotationZ": (-180, 180), "padding": (1.2, 2.5)}
fallbackAzimuths = (25, -35, 150, -150, 0, 90, -90)
unfixableScore = 2


class Scores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lighting: int
    visibility: int
    meshQuality: int
    fidelity: int
    composition: int


class RetryParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    azimuth: float
    elevation: float
    rotationZ: float
    lighting: Lighting
    padding: float


class VlmVerdict(BaseModel):
    """Exactly what the model must return; scores and issues come before the decision on purpose."""
    model_config = ConfigDict(extra="forbid")
    scores: Scores
    issues: list[str]
    action: Action
    retry: RetryParams | None
    reason: str


class Verdict(BaseModel):
    action: Action
    reason: str
    judgedBy: Literal["metrics", "vlm"]
    scores: Scores | None = None
    issues: list[str] = []
    retry: dict | None = None  # full params for the next attempt when action == "retry"
    policy: list[str] = []  # code-level overrides applied on top of the judgment
    metrics: dict = {}
    model: str | None = None


def clampParams(p):
    out = {**defaultParams, **{k: v for k, v in (p or {}).items() if k in defaultParams}}
    for k, (lo, hi) in ranges.items():
        out[k] = round(min(hi, max(lo, float(out[k]))), 1)
    if out["lighting"] not in Lighting.__args__:
        out["lighting"] = "soft"
    return out


def applyPolicy(v, params, history, attempt, maxAttempts):
    """The model decides; code keeps the loop bounded and stops it from repeating itself."""
    if v.scores and v.action != "fallback2d" and min(v.scores.meshQuality, v.scores.fidelity) <= unfixableScore:
        v.policy.append(f"meshQuality {v.scores.meshQuality} / fidelity {v.scores.fidelity}: "
                        f"a camera change cannot fix the model, overriding {v.action} → fallback2d")
        v.action = "fallback2d"
    if v.action == "retry" and attempt >= maxAttempts:
        v.policy.append(f"retry budget spent ({attempt}/{maxAttempts}) → fallback2d")
        v.action = "fallback2d"
    if v.action != "retry":
        v.retry = None
        return v
    tried = [clampParams(h["params"]) for h in history] + [clampParams(params)]
    nxt = clampParams({**params, **(v.retry or {})})
    if nxt in tried:
        used = {t["azimuth"] for t in tried}
        nxt["azimuth"] = float(next((a for a in fallbackAzimuths if a not in used), (nxt["azimuth"] + 60) % 360 - 180))
        v.policy.append(f"proposed setup was already tried; orbiting camera to azimuth {nxt['azimuth']}")
    v.retry = nxt
    return v


def judgeRender(renderPath, referencePath=None, history=(), params=None, attempt=1, maxAttempts=3, vlm=None):
    params = clampParams(params)
    m = imageMetrics(renderPath)
    gate = hardGate(m, params)
    if gate:
        issue, fix = gate
        v = Verdict(action="retry", reason=issue, judgedBy="metrics", issues=[issue], retry=fix, metrics=m)
    elif vlm is None:
        v = Verdict(action="proceed", reason="pixel checks passed (no VLM configured)", judgedBy="metrics", metrics=m)
    else:
        images = [flattenForViewing(renderPath)] + ([referencePath] if referencePath else [])
        try:
            r = vlm.askJson(judgePrompt(params, list(history), bool(referencePath)), VlmVerdict, images, judgeSystem)
            v = Verdict(action=r.action, reason=r.reason, judgedBy="vlm", scores=r.scores, issues=r.issues,
                        retry=r.retry.model_dump() if r.retry else None, metrics=m, model=vlm.model)
        except VlmError as e:
            v = Verdict(action="proceed", reason=f"pixel checks passed; VLM unavailable: {e}", judgedBy="metrics",
                        metrics=m)
    return applyPolicy(v, params, list(history), attempt, maxAttempts)
