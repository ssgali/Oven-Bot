from __future__ import annotations

import asyncio
import logging
import uuid

import discord

from .attachments import download_attachments, has_image, is_supported_attachment
from .config import Settings
from .feedback import classify_feedback
from .models import Attachment, FeedbackAction, JobStatus, ProductJob
from .pipeline import DevelopmentPipeline, Pipeline, stage_local_inputs
from .store import JobStore

LOGGER = logging.getLogger(__name__)


class OvenBot(discord.Client):
    def __init__(self, settings: Settings, store: JobStore, pipeline: Pipeline) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        intents.messages = True
        super().__init__(intents=intents)
        self.settings = settings
        self.store = store
        self.pipeline = pipeline
        self._jobs: set[asyncio.Task[None]] = set()

    async def on_ready(self) -> None:
        LOGGER.info("Connected to Discord as %s", self.user)

    def _is_allowed_submission(self, message: discord.Message) -> bool:
        if message.author.bot or not message.guild:
            return False
        if self.settings.allowed_guild_id and message.guild.id != self.settings.allowed_guild_id:
            return False
        if self.settings.input_channel_id and message.channel.id != self.settings.input_channel_id:
            return False
        return isinstance(message.channel, discord.TextChannel)

    def _attachments(self, message: discord.Message) -> list[Attachment]:
        return [
            Attachment(filename=item.filename, url=item.url, size=item.size)
            for item in message.attachments
            if is_supported_attachment(
                Attachment(item.filename, item.url, item.size),
                self.settings.image_extensions,
                self.settings.spec_extensions,
            )
        ]

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if isinstance(message.channel, discord.Thread):
            await self._handle_feedback(message)
            return
        if not self._is_allowed_submission(message):
            return
        attachments = self._attachments(message)
        if not has_image(attachments, self.settings.image_extensions):
            await message.reply("Please attach at least one product image (PNG, JPG, JPEG, or WEBP).")
            return
        guild = message.guild
        if guild is None:
            return
        thread = await message.create_thread(name=f"Ad Job - {message.id}")
        job = ProductJob(
            job_id=f"JOB-{uuid.uuid4().hex[:8].upper()}",
            guild_id=guild.id,
            channel_id=message.channel.id,
            source_message_id=message.id,
            thread_id=thread.id,
            user_id=message.author.id,
            prompt=message.content,
            attachments=attachments,
        )
        self.store.save(job)
        await thread.send(f"Received **{job.job_id}**. I am staging the product assets now.")
        task = asyncio.create_task(self._process_job(job, thread))
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    async def _process_job(self, job: ProductJob, thread: discord.Thread) -> None:
        try:
            job.update(status=JobStatus.DOWNLOADING_INPUTS, step="downloading_inputs")
            self.store.save(job)
            await download_attachments(
                job.attachments,
                self.settings.data_dir / job.job_id / "downloads",
                self.settings.max_attachment_bytes,
            )
            await stage_local_inputs(job, self.settings.data_dir)
            job.update(status=JobStatus.PROCESSING, step="pipeline")
            self.store.save(job)
            async def progress(message: str) -> None:
                await thread.send(message)

            await self.pipeline.run(job, progress)
            job.update(status=JobStatus.WAITING_FOR_APPROVAL, step="approval")
            self.store.save(job)
            await thread.send("Reply `approve` or describe a change for a targeted revision.")
        except Exception:
            LOGGER.exception("Job %s failed", job.job_id)
            job.update(status=JobStatus.FAILED, step="failed")
            self.store.save(job)
            await thread.send("The job failed while processing. Check the service logs for details.")

    async def _handle_feedback(self, message: discord.Message) -> None:
        thread = message.channel
        if not isinstance(thread, discord.Thread):
            return
        job = self.store.find_by_thread(thread.id)
        if not job or job.status not in (
            JobStatus.WAITING_FOR_APPROVAL,
            JobStatus.REVISION_REQUESTED,
        ):
            return
        action = classify_feedback(message.content)
        if action is FeedbackAction.UNKNOWN:
            await message.reply("I could not route that feedback. Try `approve`, `brighter`, `CTA is too small`, or `model is wrong`.")
            return
        if action is FeedbackAction.APPROVE:
            job.update(status=JobStatus.APPROVED, step="approved")
            self.store.save(job)
            await message.reply(f"Approved **{job.job_id}**. Final assets are ready.")
            return
        job.update(status=JobStatus.REVISION_REQUESTED, step=action.value)
        self.store.save(job)
        task = asyncio.create_task(self._revise_job(job, thread, action, message.content))
        self._jobs.add(task)
        task.add_done_callback(self._jobs.discard)

    async def _revise_job(
        self, job: ProductJob, thread: discord.Thread, action: FeedbackAction, feedback: str
    ) -> None:
        try:
            async def progress(message: str) -> None:
                await thread.send(message)

            await self.pipeline.revise(job, action, feedback, progress)
            job.update(status=JobStatus.WAITING_FOR_APPROVAL, step="approval")
            self.store.save(job)
            await thread.send("Revision is ready. Reply `approve` or request another change.")
        except Exception:
            LOGGER.exception("Revision failed for %s", job.job_id)
            job.update(status=JobStatus.FAILED, step="failed")
            self.store.save(job)
            await thread.send("The revision failed. Check the service logs for details.")


def build_bot(settings: Settings) -> OvenBot:
    return OvenBot(
        settings=settings,
        store=JobStore(settings.data_dir),
        pipeline=DevelopmentPipeline(settings.data_dir),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    build_bot(settings).run(settings.discord_token)
