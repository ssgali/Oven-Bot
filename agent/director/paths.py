from dataclasses import dataclass
from pathlib import Path


@dataclass
class JobPaths:
    """Per-revision file locations for one video job. `versionDir` is fresh each revision (mirrors
    HeroPipeline.nextVersionDir), so an earlier revision's frames/video are never overwritten."""
    versionDir: Path
    engine: str = "eevee"
    samples: int | None = None

    @property
    def rawDir(self):
        return Path(self.versionDir) / "frames" / "raw"

    @property
    def compositedDir(self):
        return Path(self.versionDir) / "frames" / "composited"

    @property
    def videoPath(self):
        return Path(self.versionDir) / "video.mp4"
