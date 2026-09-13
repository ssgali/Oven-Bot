from pathlib import Path

from oven_bot.models import Attachment, JobStatus, ProductJob
from oven_bot.store import JobStore


def test_job_store_round_trip(tmp_path: Path):
    job = ProductJob(
        job_id="JOB-1",
        guild_id=1,
        channel_id=2,
        source_message_id=3,
        thread_id=4,
        user_id=5,
        prompt="make an ad",
        attachments=[Attachment("product.png", "https://example.test/product.png", 10)],
    )
    store = JobStore(tmp_path)
    store.save(job)
    loaded = store.get("JOB-1")
    assert loaded is not None
    assert loaded.status is JobStatus.RECEIVED
    assert loaded.attachments[0].filename == "product.png"
