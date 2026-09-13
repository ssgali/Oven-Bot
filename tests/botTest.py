import asyncio
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image, ImageDraw  # noqa: E402

import bot.pipeline.heroPipeline as heroPipeline  # noqa: E402
from agent.judge import clampParams, defaultParams  # noqa: E402
from bot import (Attachment, DevPipeline, FeedbackAction, HeroPipeline, JobStatus, JobStore, ProductJob,  # noqa: E402
                 Settings, adjustRenderParams, buildBot, classifyFeedback)
from bot.intake import hasImage, isSupported, safeFilename  # noqa: E402
from compose import AdCopy, composeAll, formats  # noqa: E402
from e2eTest import check, step  # noqa: E402

A = FeedbackAction


def feedbackCases():
    cases = {
        "approved, looks good": A.APPROVE,
        "LGTM": A.APPROVE,
        "Make the lighting brighter and change the angle": A.RERENDER,
        "zoom in a bit": A.RERENDER,
        "The CTA text is too small": A.REEDIT,
        "the title should say Aurora Pro": A.REEDIT,
        "the model is wrong, use the other image": A.REGENERATE_3D,
        "this is out of context": A.UNKNOWN,  # "text" inside another word must not route to a copy edit
        "hmm, not sure": A.UNKNOWN,
    }
    for text, expected in cases.items():
        got = classifyFeedback(text)
        check(got is expected, f"{text!r}: {got} != {expected}")


def paramsCases():
    base = clampParams(defaultParams)
    p = adjustRenderParams("make it brighter", base)
    check(p["lighting"] == "highKey" and p["azimuth"] == base["azimuth"], f"brighter: {p}")
    p = adjustRenderParams("zoom in and show it from above", base)
    check(p["padding"] == 1.3 and p["elevation"] == 27.0, f"zoom in + above: {p}")
    p = adjustRenderParams("show the other side", {**base, "azimuth": 150.0})
    check(p["azimuth"] == -120.0, f"other side should wrap past 180: {p}")
    p = adjustRenderParams("render it again please", base)
    check(p["azimuth"] == base["azimuth"] + 45, f"unrecognized request should still change the view: {p}")


def intakeCases():
    images, specs = Settings.imageExtensions, Settings.specExtensions
    check(isSupported("Photo.JPG", images, specs) and isSupported("spec.pdf", images, specs), "supported types")
    check(not isSupported("notes.docx", images, specs), "docx accepted")
    check(safeFilename("../my photo?.png") == "my_photo_.png", safeFilename("../my photo?.png"))
    check(hasImage([Attachment("a.txt", "", 1), Attachment("b.webp", "", 1)], images), "webp not an image")


def productImage(path, size):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    w, h = size
    ImageDraw.Draw(img).rounded_rectangle((w * 0.2, h * 0.1, w * 0.8, h * 0.9), radius=w // 10, fill=(200, 40, 50, 255))
    img.save(path)
    return path


def makeJob(folder):
    folder.mkdir(parents=True)
    spec = folder / "spec.txt"
    spec.write_text("Wireless earbuds, 30h battery, IPX4", encoding="utf-8")
    files = [productImage(folder / "small.png", (300, 400)), productImage(folder / "big.png", (600, 800)), spec]
    return ProductJob(jobId="JOB-TEST", guildId=1, channelId=2, sourceMessageId=3, threadId=4, userId=5,
                      prompt="Aurora earbuds", attachments=[
                          Attachment(p.name, f"https://example.test/{p.name}", p.stat().st_size, str(p)) for p in files])


def storeCases(folder):
    store = JobStore(folder)
    job = makeJob(folder / "job")
    job.state = {"params": clampParams(defaultParams)}
    store.save(job)
    loaded = store.findByThread(4)
    check(loaded and loaded.status is JobStatus.RECEIVED and loaded.attachments[1].filename == "big.png"
          and loaded.state == job.state, f"round trip: {loaded}")

    busy = makeJob(folder / "busy")
    busy.jobId, busy.threadId, busy.outputs = "JOB-BUSY", 5, ["hero.png"]
    busy.update(JobStatus.REVISION_REQUESTED, "rerender")
    store.save(busy)
    recovered = {j.jobId: j.status for j in store.recoverInterrupted()}
    check(recovered == {"JOB-TEST": JobStatus.FAILED, "JOB-BUSY": JobStatus.WAITING_FOR_APPROVAL},
          f"restart recovery: {recovered}")


def wiringCases(folder):
    check(isinstance(buildBot(Settings("token", dataDir=folder, pipeline="dev")).pipeline, DevPipeline), "dev")
    check(isinstance(buildBot(Settings("token", dataDir=folder)).pipeline, HeroPipeline), "hero")


async def devCase(folder):
    job = makeJob(folder)
    messages = []

    async def progress(m):
        messages.append(m)

    pipeline = DevPipeline(Settings("token", dataDir=folder))
    await pipeline.run(job, progress)
    check(sorted(Path(o).name for o in job.outputs) == ["big.png", "small.png"], f"dev outputs {job.outputs}")
    await pipeline.revise(job, A.RERENDER, "brighter", progress)
    check(job.state["runs"] == 2 and len(messages) == 3, f"dev revise: {messages}")


class FakeBlender:
    """Stands in for BlenderClient: which products exist in the scene, and every snippet that ran."""
    scene = set()
    code = []

    def __init__(self, host, port):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def execCode(self, code, timeout=None):
        FakeBlender.code.append(code)
        if code.startswith("import bpy\nprint("):
            name = code.split("get(")[1].split(")")[0].strip("'")
            return f"{name in FakeBlender.scene}\n"
        return ""


async def heroCase(folder):
    generated, heroRuns, messages = [], [], []

    def fakeGenerate(client, imagePath, name="Product", timeout=600, onProgress=None, **kw):
        for update in ({"submitted": "uuid", "balance": 9.0}, ["Generating"], ["Generating"], ["Done"]):
            onProgress(update)
        FakeBlender.scene.add(name)
        generated.append(Path(imagePath).name)
        return {"name": name, "cost": 0.5}

    def fakeHero(client, objName, referencePath, cutoutPath=None, blurb="", productName="", outDir="out",
                 maxAttempts=3, backend="hf", engine="eevee", params=None, onEvent=print, **kw):
        params = clampParams(params)
        onEvent(f"attempt 1 {params}: proceed")
        copy = AdCopy(title=f"Render {len(heroRuns)}", specs=["30h battery"])
        heroes = composeAll(cutoutPath, copy, Path(outDir) / "hero")
        heroRuns.append({"params": params, "blurb": blurb})
        return {"source": "3d", "product": str(cutoutPath), "copy": copy.toDict(),
                "heroes": {a: h["path"] for a, h in heroes.items()},
                "attempts": [{"params": params, "verdict": {"action": "proceed", "reason": "fake judge"}}]}

    heroPipeline.BlenderClient, heroPipeline.generateModel, heroPipeline.runHero = FakeBlender, fakeGenerate, fakeHero
    heroPipeline.VlmClient = lambda backend: "fake-vlm"
    heroPipeline.writeCopy = lambda reference, blurb, vlm: (
        AdCopy(title="Render 0", specs=["30h battery"], cta="Buy Now"), {"source": "vlm", "dropped": []})

    async def progress(m):
        messages.append(m)

    def version(job):
        return Path(job.outputs[0]).parent.parent.name

    job = makeJob(folder)
    pipeline = HeroPipeline(Settings("token", dataDir=folder, vlmBackend="hf"))
    await pipeline.run(job, progress)
    check(generated == ["big.png"], f"largest image should be the 3D source: {generated}")
    check(len(job.outputs) == len(formats) and all(Path(o).is_file() for o in job.outputs), f"outputs {job.outputs}")
    check("30h battery" in heroRuns[-1]["blurb"], "spec.txt not passed to the copywriter")
    check(sum(m == "Hyper3D: Generating" for m in messages) == 1, f"repeated poll status not collapsed: {messages}")
    firstCopy = job.state["copy"]

    await pipeline.revise(job, A.RERENDER, "make it brighter", progress)
    check(generated == ["big.png"] and len(heroRuns) == 2, "rerender must reuse the model")
    check(heroRuns[-1]["params"]["lighting"] == "highKey" and job.state["copy"] == firstCopy and version(job) == "v2",
          f"rerender: {job.state}")
    check(any("hide_render" in c for c in FakeBlender.code), "other products not hidden before render")

    await pipeline.revise(job, A.REEDIT, "the CTA should say Buy Now", progress)
    check(len(heroRuns) == 2 and job.state["copy"]["cta"] == "Buy Now" and version(job) == "v3",
          f"reedit must only recompose: {job.state['copy']}")

    before = list(job.outputs)
    heroPipeline.writeCopy = lambda reference, blurb, vlm: (AdCopy(), {"source": "fallback", "reason": "offline"})
    try:
        await pipeline.revise(job, A.REEDIT, "change the title", progress)
        raised = False
    except RuntimeError:
        raised = True
    check(raised and job.outputs == before, "reedit without a copywriter should fail and keep the assets")

    await pipeline.revise(job, A.REGENERATE_3D, "the model is wrong", progress)
    check(generated == ["big.png", "small.png"], f"regenerate should move to the next image: {generated}")
    check(any("bpy.data.objects.remove" in c for c in FakeBlender.code), "old model not removed")

    FakeBlender.scene.clear()
    await pipeline.revise(job, A.RERENDER, "change the angle", progress)
    check(len(generated) == 3 and Path(job.outputs[0]).is_file(), "missing model should be generated again")
    print(f"  {len(messages)} progress messages, final outputs in {version(job)}")


def main():
    step("feedback routing", feedbackCases)
    step("render nudges from feedback", paramsCases)
    step("attachment intake", intakeCases)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        step("job store + restart recovery", lambda: storeCases(tmp / "store"))
        step("bot wiring", lambda: wiringCases(tmp / "wiring"))
        step("dev pipeline", lambda: asyncio.run(devCase(tmp / "dev")))
        step("hero pipeline: run + targeted revisions (fake Blender)", lambda: asyncio.run(heroCase(tmp / "hero")))
    print("all bot checks passed")


if __name__ == "__main__":
    main()
