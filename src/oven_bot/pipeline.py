from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Protocol

from .models import FeedbackAction, ProductJob


class ProgressSink(Protocol):
    def __call__(self, message: str) -> Awaitable[object]: ...


class Pipeline(Protocol):
    async def run(self, job: ProductJob, progress: ProgressSink) -> None: ...

    async def revise(
        self, job: ProductJob, action: FeedbackAction, feedback: str, progress: ProgressSink
    ) -> None: ...


@dataclass
class DevelopmentPipeline:
    """Runnable local pipeline seam.

    It stages inputs and emits a manifest. Replace this adapter with Meshy/Blender/Drive
    implementations without changing Discord event handling or job state.
    """

    data_dir: Path

    async def run(self, job: ProductJob, progress: ProgressSink) -> None:
        await progress("Inputs staged. The development pipeline is preparing an asset manifest.")
        await asyncio.sleep(0)
        job.outputs = []
        manifest = self.data_dir / job.job_id / "generated" / "manifest.txt"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            "Development pipeline output. Connect Meshy, Blender, and Drive adapters here.\n",
            encoding="utf-8",
        )
        job.outputs.append(str(manifest))
        await progress("Development output created. Waiting for reviewer approval.")

    async def revise(
        self, job: ProductJob, action: FeedbackAction, feedback: str, progress: ProgressSink
    ) -> None:
        await progress(
            f"Feedback classified as `{action.value}`. Re-running the affected stage: {feedback}"
        )
        await self.run(job, progress)


async def stage_local_inputs(job: ProductJob, data_dir: Path) -> None:
    destination = data_dir / job.job_id / "input"
    destination.mkdir(parents=True, exist_ok=True)
    for attachment in job.attachments:
        if attachment.local_path:
            source = Path(attachment.local_path)
            target = destination / source.name
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            attachment.local_path = str(target)
