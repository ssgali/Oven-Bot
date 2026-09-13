import asyncio
import json
import logging
import re
from pathlib import Path

from PIL import Image

from agent import VlmClient, runHero, writeCopy
from agent.judge import flattenForViewing
from blender import BlenderClient, BlenderError, generateModel
from compose import AdCopy, composeAll
from prep import hasAlpha, removeBackground
from ..feedback import adjustRenderParams, classifyFeedback
from ..jobs import FeedbackAction

log = logging.getLogger(__name__)
textSpecs = (".txt", ".csv", ".md")
maxSpecChars = 4000
maxMessageChars = 1900
priceLine = re.compile(r"^\s*price\s*[:=]\s*(.+?)\s*$", re.I | re.M)
currencyAmount = re.compile(r"[$€£₹]\s?\d[\d,]*(?:\.\d+)?")
judgedEvent = re.compile(r"^attempt (\d+) .*?: (proceed|retry|fallback2d) by")

sourceNotes = {
    "3d": "the ads use the 3D render",
    "2d": "the 3D render was rejected, so the ads use the photo cutout",
    "3d-unapproved": "the 3D render was rejected and there is no clean cutout, so the ads use the last render",
    "3d-reviewer": "the ads use the 3D render because the reviewer asked for it",
}
actionLabels = {"proceed": "approved", "retry": "retry with a new camera/lighting setup",
                "fallback2d": "rejected, fall back to the photo"}
scoreNames = {"lighting": "lighting", "visibility": "visibility", "meshQuality": "mesh", "fidelity": "fidelity",
              "composition": "composition"}

sceneHasCode = "import bpy\nprint(bpy.data.objects.get({name!r}) is not None)"

removeCode = """
import bpy
old = bpy.data.objects.get({name!r})
if old is not None:
    for o in (*old.children_recursive, old):
        bpy.data.objects.remove(o, do_unlink=True)
"""

# earlier jobs leave their products in the scene; only this job's product (plus the studio) may show up
showOnlyCode = """
import bpy
keep = bpy.data.objects[{name!r}]
wanted = {{keep, *keep.children_recursive}}
for o in bpy.data.objects:
    if o.get("ovenStudio"):
        continue
    o.hide_render = o not in wanted
    try:
        o.hide_set(o not in wanted)
    except RuntimeError:
        pass
"""


class Relay:
    """Progress from a worker thread: messages reach Discord in order, and all are posted before the block exits."""

    def __init__(self, progress):
        self.progress = progress

    async def __aenter__(self):
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue()
        self.task = asyncio.create_task(self.drain())
        return self

    async def __aexit__(self, *exc):
        self.queue.put_nowait(None)
        await self.task

    def __call__(self, message):
        self.loop.call_soon_threadsafe(self.queue.put_nowait, str(message)[:maxMessageChars])

    async def drain(self):
        while (message := await self.queue.get()) is not None:
            try:
                await self.progress(message)
            except Exception:
                log.exception("could not post progress message")


class HeroPipeline:
    """Discord job → cutout → Hyper3D model → studio render + judge loop → hero shots at 9:16, 1:1, 16:9.

    Revisions rerun only what the feedback touches: REEDIT rewrites the copy and recomposes, RERENDER nudges
    camera/lighting and renders the existing model again, REGENERATE_3D builds a new model from the next image,
    USE_3D overrides the judge and composes from the last render.
    Blender has one scene, so jobs take turns on it; blocking work runs in worker threads.
    progress(message, files=()) posts to the job thread; files are shown inline (the render previews)."""

    classify = staticmethod(classifyFeedback)

    def __init__(self, settings):
        self.settings = settings
        self.blenderTurn = asyncio.Lock()

    async def run(self, job, progress):
        images = rankImages(job, self.settings.imageExtensions)
        if not images:
            raise ValueError("none of the uploaded images could be opened")
        job.state = {"images": images, "imageIndex": 0, "version": 0}
        unread = [a.filename for a in job.attachments
                  if Path(a.filename).suffix.lower() in self.settings.specExtensions
                  and Path(a.filename).suffix.lower() not in textSpecs]
        if unread:
            await progress(f"Can't read {', '.join(unread)} yet; ad copy uses the message text and .txt/.csv specs.")
        await self.regenerate(job, progress)

    async def revise(self, job, action, feedback, progress):
        if "product" not in job.state:
            await progress("No earlier result to revise; running the whole pipeline.")
            return await self.run(job, progress)
        if action is FeedbackAction.REEDIT:
            await self.reedit(job, feedback, progress)
        elif action is FeedbackAction.RERENDER:
            params = adjustRenderParams(feedback, job.state["params"])
            await progress(f"Re-rendering the current model: {describeParams(params)}.")
            await self.rerender(job, progress, params, keepCopy=True)
        elif action is FeedbackAction.REGENERATE_3D:
            job.state["imageIndex"] += 1
            await self.regenerate(job, progress)
        elif action is FeedbackAction.USE_3D:
            await self.useRender(job, progress)
        else:
            raise ValueError(f"{action.value} is not a revision")

    async def regenerate(self, job, progress, params=None):
        s = job.state
        count = len(s["images"])
        image = Path(s["images"][s["imageIndex"] % count])
        which = f" (image {s['imageIndex'] % count + 1} of {count}, largest first)" if count > 1 else ""
        await progress(f"3D source: `{image.name}`{which}.")
        async with Relay(progress) as say:
            cutout = await asyncio.to_thread(makeCutout, image, self.jobDir(job), say)
        s.update(image=str(image), cutout=str(cutout) if cutout else None, force3d=False)
        previous = s.get("objName")
        asset = await self.inBlender(progress, lambda client, say: makeModel(
            client, say, cutout or image, job.jobId, previous, self.settings.hyper3dTimeout))
        s["objName"] = asset["name"]
        cost = f", cost {asset['cost']} credits" if asset.get("cost") is not None else ""
        await progress(f"Model imported as `{asset['name']}`{cost}. Rendering and judging hero shots…")
        await self.rerender(job, progress, params, regenerateIfMissing=False)

    async def rerender(self, job, progress, params=None, keepCopy=False, regenerateIfMissing=True):
        s = job.state
        outDir = self.nextVersionDir(job)
        blurb = specBlurb(job)

        def work(client, say):
            if not inScene(client, s["objName"]):
                return None
            client.execCode(showOnlyCode.format(name=s["objName"]))
            return runHero(client, s["objName"], s["image"], s["cutout"], blurb, outDir=outDir,
                           maxAttempts=self.settings.maxAttempts, backend=self.settings.vlmBackend,
                           engine=self.settings.engine, params=params, onEvent=relayEvents(say))

        trace = await self.inBlender(progress, work)
        if trace is None:
            if not regenerateIfMissing:
                raise BlenderError(f"{s['objName']} is missing from the Blender scene right after import")
            await progress(f"`{s['objName']}` is no longer in the Blender scene; generating the model again.")
            return await self.regenerate(job, progress, params)

        attempts = trace["attempts"]
        render, product, source = attempts[-1]["render"], trace["product"], trace["source"]
        if s.get("force3d") and source != "3d":
            product, source = render, "3d-reviewer"
        # a camera change shouldn't reword an ad the reviewer already read
        copy = withPrice(s["copy"] if keepCopy and s.get("copy") else trace["copy"], blurb)
        heroes = trace["heroes"]
        if product != trace["product"] or copy != trace["copy"]:
            heroes = await asyncio.to_thread(composeHeroes, product, copy, outDir)
        s.update(copy=copy, params=attempts[-1]["params"], product=product, source=source, render=render)
        job.outputs = list(heroes.values())

        previews = await asyncio.to_thread(renderPreviews, [a["render"] for a in attempts])
        await progress(describeAttempts(s["objName"], attempts), files=previews)
        hint = "\nReply `use the 3d render` to build the ads from the render anyway." if source == "2d" else ""
        await progress(f"**Ad copy**\n{describeCopy(AdCopy.fromDict(copy))}\n\n"
                       f"**Result:** {sourceNotes.get(source, source)}.{hint}")

    async def useRender(self, job, progress):
        s = job.state
        if not (s.get("render") and Path(s["render"]).is_file()):
            raise RuntimeError("this job has no 3D render to use yet")
        heroes = await asyncio.to_thread(composeHeroes, s["render"], s["copy"], self.nextVersionDir(job))
        s.update(product=s["render"], source="3d-reviewer", force3d=True)
        job.outputs = list(heroes.values())
        await progress("Hero shots rebuilt from the 3D render. Later camera/lighting changes keep using the render; "
                       "`the model is wrong` goes back to letting the judge decide.")

    async def reedit(self, job, feedback, progress):
        s = job.state
        blurb = (f"{specBlurb(job)}\n\nCurrent ad copy: {json.dumps(s['copy'])}\n"
                 f"Reviewer change request: {feedback}\nApply the request and keep the rest of the copy.")

        def write():
            vlm = None if self.settings.vlmBackend == "metrics" else VlmClient(self.settings.vlmBackend)
            return writeCopy(s["image"], blurb, vlm)

        copy, info = await asyncio.to_thread(write)
        if info["source"] != "vlm":
            raise RuntimeError(f"copy edits need the copywriter model, which is unavailable: {info['reason']}")
        copy.price = copy.price or s["copy"].get("price", "")
        s["copy"] = copy.toDict()
        heroes = await asyncio.to_thread(composeHeroes, s["product"], s["copy"], self.nextVersionDir(job))
        job.outputs = list(heroes.values())
        dropped = f"\nDropped (numbers not in the brief): {', '.join(info['dropped'])}" if info.get("dropped") else ""
        await progress(f"**New ad copy**\n{describeCopy(copy)}{dropped}")

    async def inBlender(self, progress, work):
        """work(client, say) runs in a worker thread while this job has its turn on the Blender scene."""
        if self.blenderTurn.locked():
            await progress("Blender is busy with another job; waiting for it to finish.")
        async with self.blenderTurn, Relay(progress) as say:
            return await asyncio.to_thread(self.withClient, work, say)

    def withClient(self, work, say):
        with BlenderClient(self.settings.blenderHost, self.settings.blenderPort) as client:
            return work(client, say)

    def jobDir(self, job):
        return Path(self.settings.dataDir) / job.jobId

    def nextVersionDir(self, job):
        job.state["version"] += 1
        return self.jobDir(job) / f"v{job.state['version']}"


def rankImages(job, imageExtensions):
    """Largest first: Hyper3D gets the most detail out of the highest-resolution photo."""
    sized = []
    for a in job.attachments:
        if not a.localPath or Path(a.localPath).suffix.lower() not in imageExtensions:
            continue
        try:
            with Image.open(a.localPath) as img:
                sized.append((img.width * img.height, a.localPath))
        except OSError:
            log.warning("skipping unreadable image %s", a.localPath)
    return [path for _, path in sorted(sized, key=lambda s: -s[0])]


def specBlurb(job):
    parts = [job.prompt.strip()]
    for a in job.attachments:
        if a.localPath and Path(a.localPath).suffix.lower() in textSpecs:
            parts.append(Path(a.localPath).read_text(encoding="utf-8", errors="replace")[:maxSpecChars].strip())
    return "\n\n".join(p for p in parts if p)


def withPrice(copy, blurb):
    """writeCopy never fills the price; take it from a `Price:` line or a currency amount in the brief."""
    if copy.get("price"):
        return copy
    m = priceLine.search(blurb)
    price = m.group(1) if m else (currencyAmount.search(blurb) or [""])[0]
    return {**copy, "price": price[:20]} if price else copy


def makeCutout(image, jobDir, say):
    """Transparent PNG for Hyper3D and the 2D fallback; None when the mask looks wrong."""
    if hasAlpha(image):
        say(f"`{image.name}` already has transparency; skipping background removal.")
        return image
    say("Removing the background…")
    r = removeBackground(image, Path(jobDir) / f"{image.stem}Cutout.png")
    if not 0.02 < r["coverage"] < 0.95:
        say(f"Background removal looks wrong (product covers {r['coverage']:.0%} of the photo); "
            "sending the original photo to Hyper3D, and there will be no 2D fallback.")
        return None
    return Path(r["outPath"])


def makeModel(client, say, source, name, previous, timeout):
    if previous:
        client.execCode(removeCode.format(name=previous))
    last = []

    def onProgress(update):
        if isinstance(update, dict):
            if "submitted" in update:
                text = f"Model request sent to {update['submitted']}…" if update.get("submitted") else "Model job submitted."
            elif "downloaded" in update:
                text = f"Model received ({update['downloaded']} bytes); importing…"
            else:
                text = f"Model job submitted (balance {update.get('balance')} credits)."
        else:
            text = f"Model: {sum(s == 'Done' for s in update)}/{len(update)} steps done"
        if last[-1:] != [text]:
            last.append(text)
            say(text)

    return generateModel(client, source, name, timeout=timeout, onProgress=onProgress)


def relayEvents(say):
    """heroLoop's events are debug text (dicts, raw params): log them, and only tell the thread when an attempt is
    judged, so a slow loop still shows signs of life. The formatted summary is posted once the loop is done."""
    def onEvent(text):
        log.info("heroLoop: %s", text)
        m = judgedEvent.match(text)
        if m:
            say(f"Render attempt {m.group(1)}: {actionLabels.get(m.group(2), m.group(2))}.")
    return onEvent


def inScene(client, name):
    return client.execCode(sceneHasCode.format(name=name)).strip().endswith("True")


def renderPreviews(renders):
    """Transparent renders of dark products vanish on Discord's dark theme; flatten onto the judge's gray."""
    previews = []
    for render in map(Path, renders):
        if render.is_file():
            preview = render.with_name(f"{render.stem}Preview.jpg")
            flattenForViewing(render, maxSize=1200).save(preview, quality=90)
            previews.append(str(preview))
    return previews


def composeHeroes(product, copy, outDir):
    return {aspect: r["path"] for aspect, r in composeAll(product, AdCopy.fromDict(copy), Path(outDir) / "hero").items()}


def describeParams(p):
    return (f"{p['lighting']} light · azimuth {p['azimuth']:g}° · elevation {p['elevation']:g}° · "
            f"rotation {p['rotationZ']:g}° · padding {p['padding']:g}")


def describeAttempts(objName, attempts):
    lines = [f"**Blender render{'s' if len(attempts) > 1 else ''} of `{objName}`**"]
    for i, a in enumerate(attempts, 1):
        v = a["verdict"]
        judge = v.get("model") or ("pixel checks" if v.get("judgedBy") == "metrics" else "the judge")
        lines += [f"\n**Attempt {i}**: {describeParams(a['params'])}",
                  f"→ {actionLabels.get(v['action'], v['action'])} (by {judge})"]
        if v.get("scores"):
            lines.append("Scores: " + " · ".join(f"{scoreNames.get(k, k)} {n}/5" for k, n in v["scores"].items()))
        lines.append(f"> {v['reason']}")
        lines += [f"Policy: {p}" for p in v.get("policy") or []]
    return "\n".join(lines)


def describeCopy(c):
    return (f"**{c.title}**" + (f"\n{c.tagline}" if c.tagline else "") + "".join(f"\n• {s}" for s in c.specs)
            + f"\nCTA: {c.cta}" + (f" · {c.price}" if c.price else ""))
