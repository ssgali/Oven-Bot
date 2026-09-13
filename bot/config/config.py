import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

pipelines = ("hero", "dev", "video")
vlmBackends = ("hf", "ollama", "metrics")
directorBackends = ("ollama", "hf")
engines = ("eevee", "cycles")
videoAspects = ("1:1", "4:5", "9:16", "16:9")


def optionalInt(value):
    return int(value) if value else None


def extensions(value, defaults):
    if not value:
        return defaults
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


def choice(name, default, allowed):
    value = os.getenv(name, default).strip()
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")
    return value


@dataclass(frozen=True)
class Settings:
    discordToken: str
    inputChannelId: int | None = None
    allowedGuildId: int | None = None
    dataDir: Path = Path("data")
    maxAttachmentBytes: int = 25_000_000
    imageExtensions: tuple = (".png", ".jpg", ".jpeg", ".webp")
    specExtensions: tuple = (".pdf", ".txt", ".csv", ".xlsx")
    pipeline: str = "hero"
    blenderHost: str = "localhost"
    blenderPort: int = 9876
    engine: str = "eevee"
    maxAttempts: int = 3
    hyper3dTimeout: int = 600
    vlmBackend: str = "hf"
    directorBackend: str = "ollama"
    videoFps: int = 30
    videoAspect: str = "9:16"
    videoLongEdge: int = 1080

    @classmethod
    def fromEnv(cls):
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("DISCORD_TOKEN is required")
        return cls(
            discordToken=token,
            inputChannelId=optionalInt(os.getenv("DISCORD_INPUT_CHANNEL_ID")),
            allowedGuildId=optionalInt(os.getenv("DISCORD_ALLOWED_GUILD_ID")),
            dataDir=Path(os.getenv("DATA_DIR", "data")).resolve(),
            maxAttachmentBytes=int(os.getenv("MAX_ATTACHMENT_BYTES", "25000000")),
            imageExtensions=extensions(os.getenv("SUPPORTED_IMAGE_EXTENSIONS", ""), cls.imageExtensions),
            specExtensions=extensions(os.getenv("SUPPORTED_SPEC_EXTENSIONS", ""), cls.specExtensions),
            pipeline=choice("OVEN_PIPELINE", "hero", pipelines),
            blenderHost=os.getenv("OVEN_BLENDER_HOST", "localhost"),
            blenderPort=int(os.getenv("OVEN_BLENDER_PORT", "9876")),
            engine=choice("OVEN_RENDER_ENGINE", "eevee", engines),
            maxAttempts=int(os.getenv("OVEN_HERO_ATTEMPTS", "3")),
            hyper3dTimeout=int(os.getenv("OVEN_HYPER3D_TIMEOUT", "600")),
            vlmBackend=choice("OVEN_VLM_BACKEND", "hf", vlmBackends),
            directorBackend=choice("OVEN_DIRECTOR_BACKEND", "ollama", directorBackends),
            videoFps=int(os.getenv("OVEN_VIDEO_FPS", "30")),
            videoAspect=choice("OVEN_VIDEO_ASPECT", "9:16", videoAspects),
            videoLongEdge=int(os.getenv("OVEN_VIDEO_LONG_EDGE", "1080")),
        )
