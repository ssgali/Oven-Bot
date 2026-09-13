from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utcNow():
    return datetime.now(timezone.utc).isoformat()


class JobStatus(str, Enum):
    RECEIVED = "received"
    DOWNLOADING_INPUTS = "downloading_inputs"
    PROCESSING = "processing"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    REVISION_REQUESTED = "revision_requested"
    APPROVED = "approved"
    FAILED = "failed"


inFlight = (JobStatus.RECEIVED, JobStatus.DOWNLOADING_INPUTS, JobStatus.PROCESSING, JobStatus.REVISION_REQUESTED)


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
    localPath: str | None = None


@dataclass
class ProductJob:
    jobId: str
    guildId: int
    channelId: int
    sourceMessageId: int
    threadId: int | None
    userId: int
    prompt: str
    attachments: list[Attachment]
    status: JobStatus = JobStatus.RECEIVED
    step: str = "received"
    outputs: list[str] = field(default_factory=list)  # files posted for review
    state: dict = field(default_factory=dict)  # owned by the pipeline: what a later revision needs to reuse
    createdAt: str = field(default_factory=utcNow)
    updatedAt: str = field(default_factory=utcNow)

    def update(self, status, step):
        self.status, self.step, self.updatedAt = status, step, utcNow()

    def toDict(self):
        return {**asdict(self), "status": self.status.value}

    @classmethod
    def fromDict(cls, d):
        return cls(**{**d, "status": JobStatus(d["status"]), "attachments": [Attachment(**a) for a in d["attachments"]]})
