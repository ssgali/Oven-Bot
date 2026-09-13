import json
from pathlib import Path

from blender import renderStill, setupStudio
from compose import composeAll
from ..copywriter import writeCopy
from ..judge import clampParams, defaultParams, judgeRender
from ..vlm import VlmClient


def makeVlm(backend):
    return None if backend in (None, "metrics") else VlmClient(backend)


def runHero(client, objName, referencePath, cutoutPath=None, blurb="", productName="", outDir="out",
            maxAttempts=3, backend="hf", engine="eevee", params=None, onEvent=print, judge=judgeRender):
    """render → judge → proceed | retry with the judge's setup | fall back to the 2D cutout → hero shots.
    Every decision lands in <outDir>/decisions.json. `judge` has judgeRender's signature (tests inject one)."""
    out = Path(outDir)
    out.mkdir(parents=True, exist_ok=True)
    tracePath = out / "decisions.json"
    vlm = makeVlm(backend)
    copy, copyInfo = writeCopy(referencePath, blurb, vlm, productName)
    onEvent(f"copy ({copyInfo['source']}): {copy.toDict()}")

    history = []
    trace = {"objName": objName, "backend": backend, "model": vlm.model if vlm else None, "maxAttempts": maxAttempts,
             "copy": copy.toDict(), "copyInfo": copyInfo, "attempts": history}
    save = lambda: tracePath.write_text(json.dumps(trace, indent=2), encoding="utf-8")
    params = clampParams({**defaultParams, **(params or {})})

    for attempt in range(1, maxAttempts + 1):
        setupStudio(client, objName, aspect="1:1", longEdge=1600, **params)
        renderPath = out / f"render{attempt}.png"
        r = renderStill(client, renderPath, engine=engine, transparent=True)
        v = judge(renderPath, referencePath, history, params, attempt, maxAttempts, vlm)
        history.append({"attempt": attempt, "params": params, "render": str(renderPath),
                        "renderSeconds": r["seconds"], "verdict": v.model_dump()})
        save()
        onEvent(f"attempt {attempt} {params}: {v.action} by {v.judgedBy} — {v.reason}"
                + "".join(f"\n  policy: {p}" for p in v.policy))
        if v.action != "retry":
            break
        params = v.retry

    source, product = ("3d", renderPath) if v.action == "proceed" else ("2d", cutoutPath)
    if source == "2d" and not (cutoutPath and Path(cutoutPath).is_file()):
        source, product = "3d-unapproved", renderPath
        onEvent("fallback2d requested but no cutout was given; composing the last render instead")
    heroes = composeAll(product, copy, out / "hero", stem="hero")
    trace.update(source=source, product=str(product), heroes={a: h["path"] for a, h in heroes.items()})
    save()
    return trace
