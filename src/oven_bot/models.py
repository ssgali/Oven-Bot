from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStatus(str, Enum):
    RECEIVED = "received"
    DOWNLOADING_INPUTS = "downloading_inputs"
    PROCESSING = "processing"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    REVISION_REQUESTED = "revision_requested"
    APPROVED = "approved"
    FAILED = "failed"


class FeedbackAction(str, Enum):
    APPROVE = "approve"
    RERENDER = "rerender"
    REEDIT = "reedit"
    REGENERATE_3D = "regenerate_3d"
    UNKNOWN = "unknown"


@dataclass
class Attachment:
    filename: str
    url: str
    size: int
    local_path: str | None = None


@dataclass
class ProductJob:
    job_id: str
    guild_id: int
    channel_id: int
    source_message_id: int
    thread_id: int | None
    user_id: int
    prompt: str
    attachments: list[Attachment]
    status: JobStatus = JobStatus.RECEIVED
    current_step: str = "received"
    drive_url: str | None = None
    outputs: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def update(self, *, status: JobStatus, step: str) -> None:
        self.status = status
        self.current_step = step
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProductJob":
        payload = dict(payload)
        payload["status"] = JobStatus(payload["status"])
        payload["attachments"] = [Attachment(**item) for item in payload["attachments"]]
        return cls(**payload)
