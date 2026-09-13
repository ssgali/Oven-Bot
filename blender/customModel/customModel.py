import base64
import os
import tempfile
from pathlib import Path

import requests

from ..client import BlenderError

scriptsDir = Path(__file__).parent / "blenderScripts"
imageTypes = {".png", ".jpg", ".jpeg", ".webp"}


def generateModel(client, imagePath, name="Product", endpoint=None, timeout=180, onProgress=None):
    """Drop-in replacement for blender.hyper3d.generateModel: POSTs the product photo (base64) to a
    self-hosted image->GLB endpoint (synchronous, no polling/credits) and imports the returned .glb into
    the live Blender scene under `name`. Same call shape as Hyper3D's generateModel(client, imagePath,
    name, timeout=..., onProgress=...) so it's a straight swap in the pipelines."""
    endpoint = endpoint or os.getenv("OVEN_MODEL_ENDPOINT")
    if not endpoint:
        raise ValueError("OVEN_MODEL_ENDPOINT is not set (endpoint URL for the custom image->GLB model)")

    path = Path(imagePath)
    if not path.is_file() or path.suffix.lower() not in imageTypes:
        raise BlenderError(f"not a usable image: {path}")

    if onProgress:
        onProgress({"submitted": endpoint})
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    try:
        r = requests.post(endpoint, json={"image": b64}, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        raise BlenderError(f"custom model endpoint failed: {e}") from e

    fd, glbPath = tempfile.mkstemp(suffix=".glb")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(r.content)
        if onProgress:
            onProgress({"downloaded": len(r.content)})
        result = client.runScript(scriptsDir / "importGlb.py", {"path": glbPath, "name": name}, timeout=300)
    finally:
        Path(glbPath).unlink(missing_ok=True)
    return {"name": result["name"], "cost": None}
