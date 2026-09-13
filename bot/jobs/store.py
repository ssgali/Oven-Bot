import json
from pathlib import Path

from .models import JobStatus, ProductJob, inFlight


class JobStore:
    """All jobs in one JSON file; enough for a single bot process."""

    def __init__(self, dataDir):
        self.path = Path(dataDir) / "jobs.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def save(self, job):
        jobs = self.read()
        jobs[job.jobId] = job.toDict()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(jobs, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, jobId):
        d = self.read().get(jobId)
        return ProductJob.fromDict(d) if d else None

    def all(self):
        return [ProductJob.fromDict(d) for d in self.read().values()]

    def findByThread(self, threadId):
        return next((job for job in self.all() if job.threadId == threadId), None)

    def recoverInterrupted(self):
        """Nothing is running after a restart: reopen jobs that still have assets to review, fail the rest."""
        recovered = []
        for job in self.all():
            if job.status in inFlight:
                job.update(JobStatus.WAITING_FOR_APPROVAL if job.outputs else JobStatus.FAILED, "interrupted")
                self.save(job)
                recovered.append(job)
        return recovered
