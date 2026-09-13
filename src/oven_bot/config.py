from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _optional_int(value: str | None) -> int | None:
    return int(value) if value else None


def _extensions(value: str, defaults: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return defaults
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    discord_token: str
    input_channel_id: int | None
    allowed_guild_id: int | None
    data_dir: Path
    max_attachment_bytes: int
    image_extensions: tuple[str, ...]
    spec_extensions: tuple[str, ...]

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ValueError("DISCORD_TOKEN is required")
        return cls(
            discord_token=token,
            input_channel_id=_optional_int(os.getenv("DISCORD_INPUT_CHANNEL_ID")),
            allowed_guild_id=_optional_int(os.getenv("DISCORD_ALLOWED_GUILD_ID")),
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            max_attachment_bytes=int(os.getenv("MAX_ATTACHMENT_BYTES", "25000000")),
            image_extensions=_extensions(
                os.getenv("SUPPORTED_IMAGE_EXTENSIONS", ""),
                (".png", ".jpg", ".jpeg", ".webp"),
            ),
            spec_extensions=_extensions(
                os.getenv("SUPPORTED_SPEC_EXTENSIONS", ""),
                (".pdf", ".txt", ".csv", ".xlsx"),
            ),
        )
