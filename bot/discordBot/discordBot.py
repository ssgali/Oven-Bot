import asyncio
import logging
import uuid
from pathlib import Path

import discord

from ..config import Settings
from ..feedback import classifyFeedback
from ..intake import downloadAttachments, hasImage, isSupported
from ..jobs import Attachment, FeedbackAction, JobStatus, JobStore, ProductJob, inFlight
from ..pipeline import DevPipeline, HeroPipeline

log = logging.getLogger(__name__)
maxContent = 2000
filesPerMessage = 10


def clip(text):
    return text if len(text) <= maxContent else text[:maxContent - 1] + "…"


class OvenBot(discord.Client):
    """Discord transport only: one thread per job, downloads, approval loop. The pipeline does the work."""

    def __init__(self, settings, store, pipeline):
        intents = discord.Intents.default()
        intents.message_content = True
        # model-written copy and error text are echoed into threads; never let them ping anyone
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.settings, self.store, self.pipeline = settings, store, pipeline
        self.tasks = set()

    async def setup_hook(self):
        for job in self.store.recoverInterrupted():
            log.warning("%s was interrupted by a restart; now %s", job.jobId, job.status.value)

    async def on_ready(self):
        log.info("connected to Discord as %s with %s", self.user, type(self.pipeline).__name__)

    async def on_message(self, message):
        if message.author.bot:
            return
        if isinstance(message.channel, discord.Thread):
            await self.handleFeedback(message)
        elif self.isSubmission(message):
            await self.startJob(message)

    def isSubmission(self, message):
        s = self.settings
        return (isinstance(message.channel, discord.TextChannel) and message.guild is not None
                and s.allowedGuildId in (None, message.guild.id) and s.inputChannelId in (None, message.channel.id))

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def poster(self, thread):
        async def post(message, files=()):
            attached = [discord.File(p) for p in files if Path(p).is_file()][:filesPerMessage]
            await thread.send(clip(message), **({"files": attached} if attached else {}))
        return post

    async def startJob(self, message):
        s = self.settings
        attachments = [Attachment(a.filename, a.url, a.size) for a in message.attachments
                       if isSupported(a.filename, s.imageExtensions, s.specExtensions)]
        if not hasImage(attachments, s.imageExtensions):
            if s.inputChannelId:  # only nag in a dedicated intake channel, not in every channel the bot can read
                kinds = ", ".join(e.lstrip(".").upper() for e in s.imageExtensions)
                await message.reply(f"Please attach at least one product image ({kinds}).")
            return
        job = ProductJob(jobId=f"JOB-{uuid.uuid4().hex[:8].upper()}", guildId=message.guild.id,
                         channelId=message.channel.id, sourceMessageId=message.id, threadId=None,
                         userId=message.author.id, prompt=message.content, attachments=attachments)
        thread = await message.create_thread(name=f"Ad job {job.jobId}")
        job.threadId = thread.id
        self.store.save(job)
        await thread.send(f"Received **{job.jobId}** with {len(attachments)} file(s). Downloading…")
        self.spawn(self.processJob(job, thread))

    async def processJob(self, job, thread):
        try:
            job.update(JobStatus.DOWNLOADING_INPUTS, "downloading")
            self.store.save(job)
            await downloadAttachments(job.attachments, Path(self.settings.dataDir) / job.jobId / "input",
                                      self.settings.maxAttachmentBytes)
            job.update(JobStatus.PROCESSING, "pipeline")
            self.store.save(job)
            await self.pipeline.run(job, self.poster(thread))
            await self.deliver(job, thread, "Reply `approve`, or describe a change for a targeted revision.")
        except Exception as e:
            await self.fail(job, thread, e, "failed", JobStatus.FAILED)

    async def handleFeedback(self, message):
        job = self.store.findByThread(message.channel.id)
        if job is None:
            return
        action = classifyFeedback(message.content)
        if job.status in inFlight:
            if action is not FeedbackAction.UNKNOWN:
                await message.reply(f"Still working on **{job.jobId}**; send that again once the current step is posted.")
            return
        if job.status is not JobStatus.WAITING_FOR_APPROVAL:
            return
        if action is FeedbackAction.UNKNOWN:
            await message.reply("I couldn't route that. Try `approve`, `make it brighter`, `change the angle`, "
                                "`the CTA should say Buy Now`, `use the 3d render`, or `the model is wrong`.")
            return
        if action is FeedbackAction.APPROVE:
            job.update(JobStatus.APPROVED, "approved")
            self.store.save(job)
            await message.reply(f"Approved **{job.jobId}**. The final assets are the ones posted above.")
            return
        job.update(JobStatus.REVISION_REQUESTED, action.value)
        self.store.save(job)
        await message.reply(f"Routing that as `{action.value}`.")
        self.spawn(self.reviseJob(job, message.channel, action, message.content))

    async def reviseJob(self, job, thread, action, feedback):
        try:
            await self.pipeline.revise(job, action, feedback, self.poster(thread))
            await self.deliver(job, thread, "Revision ready. Reply `approve` or request another change.")
        except Exception as e:
            # the last posted assets are still valid, so the reviewer can ask again instead of starting over
            await self.fail(job, thread, e, "revision failed",
                            JobStatus.WAITING_FOR_APPROVAL if job.outputs else JobStatus.FAILED)

    async def deliver(self, job, thread, prompt):
        limit = thread.guild.filesize_limit
        paths = [Path(p) for p in job.outputs]
        files = [p for p in paths if p.is_file() and p.stat().st_size <= limit]
        for i in range(0, len(files), filesPerMessage):
            await thread.send(files=[discord.File(p, filename=f"{job.jobId}_{p.name}")
                                     for p in files[i:i + filesPerMessage]])
        skipped = [p.name for p in paths if p not in files]
        note = f"\nNot attached (missing or over {limit // 1_000_000} MB): {', '.join(skipped)}" if skipped else ""
        job.update(JobStatus.WAITING_FOR_APPROVAL, "approval")
        self.store.save(job)
        await thread.send(clip(prompt + note))

    async def fail(self, job, thread, error, what, status):
        log.error("%s %s", job.jobId, what, exc_info=error)
        job.update(status, what.replace(" ", "_"))
        self.store.save(job)
        hint = (" The assets posted earlier are still current: request another change or `approve`."
                if status is JobStatus.WAITING_FOR_APPROVAL else "")
        await thread.send(clip(f"**{job.jobId}** {what}: {type(error).__name__}: {str(error)[:1500]}{hint}"))


def buildBot(settings):
    pipeline = HeroPipeline(settings) if settings.pipeline == "hero" else DevPipeline(settings)
    return OvenBot(settings, JobStore(settings.dataDir), pipeline)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.fromEnv()
    Path(settings.dataDir).mkdir(parents=True, exist_ok=True)
    buildBot(settings).run(settings.discordToken, log_handler=None)
