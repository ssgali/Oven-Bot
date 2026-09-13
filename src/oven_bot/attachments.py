from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .models import Attachment


def is_supported_attachment(
    attachment: Attachment, image_extensions: tuple[str, ...], spec_extensions: tuple[str, ...]
) -> bool:
    suffix = Path(urlparse(attachment.filename).path).suffix.lower()
    return suffix in image_extensions or suffix in spec_extensions


def has_image(
    attachments: list[Attachment], image_extensions: tuple[str, ...]
) -> bool:
    return any(Path(item.filename).suffix.lower() in image_extensions for item in attachments)


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "attachment"


async def download_attachments(
    attachments: list[Attachment], destination: Path, max_bytes: int
) -> list[Attachment]:
    destination.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        for item in attachments:
            if item.size > max_bytes:
                raise ValueError(f"Attachment exceeds {max_bytes} bytes: {item.filename}")
            target = destination / safe_filename(item.filename)
            async with client.stream("GET", item.url) as response:
                response.raise_for_status()
                written = 0
                with target.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError(f"Attachment exceeds {max_bytes} bytes: {item.filename}")
                        output.write(chunk)
            item.local_path = str(target)
    return attachments
