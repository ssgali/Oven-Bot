import asyncio
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent.director import buildDirectorGraph
from blender import BlenderClient
from ..feedback import isApproval
from ..jobs import FeedbackAction
from .heroPipeline import Relay, makeCutout, makeModel, rankImages, specBlurb


class VideoPipeline:
    """Discord job -> cutout -> Hyper3D model -> LangGraph director agent (script -> render -> approval loop).

    Implements the same (job, progress) / (job, action, feedback, progress) contract documented in
    pipeline.py, so it drops into buildBot() exactly like DevPipeline/HeroPipeline. Unlike the stills
    pipeline, frames live in one fixed directory for the job's whole life: a scoped revision (see
    agent/director/graph.py's revise_script node) overwrites only the frame files it actually re-rendered,
    which is the entire point of the scoped-rerender agent step.

    classify() routes every non-approval reply straight to revise() with the raw text, instead of the
    keyword router the stills pipeline uses — the director agent interprets the critique itself."""

    classify = staticmethod(lambda text: FeedbackAction.APPROVE if isApproval(text) else FeedbackAction.REVISE)

    def __init__(self, settings):
        self.settings = settings
        self.blenderTurn = asyncio.Lock()
        conn = sqlite3.connect(str(Path(settings.dataDir) / "videoGraph.sqlite"), check_same_thread=False)
        self.graph = buildDirectorGraph(SqliteSaver(conn))

    async def run(self, job, progress):
        s = self.settings
        images = rankImages(job, s.imageExtensions)
        if not images:
            raise ValueError("none of the uploaded images could be opened")
        image = Path(images[0])
        blurb = specBlurb(job)
        async with Relay(progress) as say:
            cutout = await asyncio.to_thread(makeCutout, image, self.jobDir(job), say)
        source = str(cutout or image)

        def work(client, say):
            asset = makeModel(client, say, cutout or image, job.jobId, None, s.hyper3dTimeout)
            initial = {
                "jobId": job.jobId, "images": [source], "specBlurb": blurb, "objName": asset["name"],
                "fps": s.videoFps, "aspect": s.videoAspect, "longEdge": s.videoLongEdge, "engine": s.engine,
                "samples": s.videoSamples, "versionDir": str(self.jobDir(job) / "video"), "script": {},
                "scriptHistory": [],
                "videoPath": None, "critique": None, "critiqueHistory": [],
            }
            self.graph.invoke(initial, self.configFor(job, client, say))

        await self.inBlender(progress, work)
        job.outputs = [self.currentVideoPath(job)]

    async def revise(self, job, action, feedback, progress):
        def work(client, say):
            self.graph.invoke(Command(resume=feedback), self.configFor(job, client, say))

        await self.inBlender(progress, work)
        job.outputs = [self.currentVideoPath(job)]

    def configFor(self, job, client, say):
        s = self.settings
        return {"configurable": {"thread_id": job.jobId, "client": client, "progress": say,
                                 "scriptBackend": s.directorBackend, "reviseBackend": s.directorBackend}}

    def currentVideoPath(self, job):
        snapshot = self.graph.get_state({"configurable": {"thread_id": job.jobId}})
        return snapshot.values["videoPath"]

    async def inBlender(self, progress, work):
        """work(client, say) runs in a worker thread while this job has its turn on the Blender scene
        (mirrors HeroPipeline.inBlender; each pipeline keeps its own lock since only one pipeline runs
        per bot process, so there is no cross-pipeline Blender contention to guard against)."""
        if self.blenderTurn.locked():
            await progress("Blender is busy with another job; waiting for it to finish.")
        async with self.blenderTurn, Relay(progress) as say:
            await asyncio.to_thread(self.withClient, work, say)

    def withClient(self, work, say):
        with BlenderClient(self.settings.blenderHost, self.settings.blenderPort) as client:
            return work(client, say)

    def jobDir(self, job):
        return Path(self.settings.dataDir) / job.jobId
