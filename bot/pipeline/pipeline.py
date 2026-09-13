"""A pipeline is any object with

    async run(job, progress)                        first pass over a freshly downloaded job
    async revise(job, action, feedback, progress)   targeted rerun for a FeedbackAction

It sets job.outputs to the files the bot posts for review and keeps whatever a later revision needs in job.state.
progress(message) posts to the job's Discord thread. Raising fails the job (or the revision) with the error shown."""

from pathlib import Path


class DevPipeline:
    """No Blender: posts the uploaded images back, so intake, approval and revisions can be tried on a server."""

    def __init__(self, settings):
        self.settings = settings

    async def run(self, job, progress):
        job.outputs = [a.localPath for a in job.attachments
                       if a.localPath and Path(a.localPath).suffix.lower() in self.settings.imageExtensions]
        job.state["runs"] = job.state.get("runs", 0) + 1
        await progress(f"Dev pipeline, run {job.state['runs']}: echoing {len(job.outputs)} uploaded image(s).")

    async def revise(self, job, action, feedback, progress):
        await progress(f"Routed as `{action.value}`; the dev pipeline just runs again.")
        await self.run(job, progress)
