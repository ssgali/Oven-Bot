import re
from pathlib import Path

import httpx


def suffix(filename):
    return Path(filename).suffix.lower()


def isSupported(filename, imageExtensions, specExtensions):
    return suffix(filename) in imageExtensions or suffix(filename) in specExtensions


def hasImage(attachments, imageExtensions):
    return any(suffix(a.filename) in imageExtensions for a in attachments)


def safeFilename(filename):
    return re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name) or "attachment"


async def downloadAttachments(attachments, destination, maxBytes):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    used = set()
    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        for i, item in enumerate(attachments):
            if item.size > maxBytes:
                raise ValueError(f"{item.filename} is over {maxBytes} bytes")
            name = safeFilename(item.filename)
            if name.lower() in used:  # Discord allows two uploads with the same name
                name = f"{i}_{name}"
            used.add(name.lower())
            target = destination / name
            written = 0
            async with client.stream("GET", item.url) as response:
                response.raise_for_status()
                with target.open("wb") as out:
                    async for chunk in response.aiter_bytes():
                        written += len(chunk)
                        if written > maxBytes:
                            raise ValueError(f"{item.filename} is over {maxBytes} bytes")
                        out.write(chunk)
            item.localPath = str(target)
    return attachments
