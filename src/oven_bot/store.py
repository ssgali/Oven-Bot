from __future__ import annotations

import json
from pathlib import Path

from .models import ProductJob


class JobStore:
    """Small JSON-backed store; replaceable with a database repository later."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "jobs.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, job: ProductJob) -> None:
        jobs = self._read()
        jobs[job.job_id] = job.to_dict()
        self.path.write_text(json.dumps(jobs, indent=2), encoding="utf-8")

    def get(self, job_id: str) -> ProductJob | None:
        payload = self._read().get(job_id)
        return ProductJob.from_dict(payload) if payload else None

    def find_by_thread(self, thread_id: int) -> ProductJob | None:
        for payload in self._read().values():
            if payload.get("thread_id") == thread_id:
                return ProductJob.from_dict(payload)
        return None
