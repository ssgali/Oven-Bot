import base64
import time
from pathlib import Path

from ..client import BlenderError
from .status import checkBalance, ensureReady, explainFailure

imageTypes = {".png", ".jpg", ".jpeg", ".webp"}


def normalizeBbox(bbox):
    if bbox is None:
        return None
    if len(bbox) != 3 or any(v <= 0 for v in bbox):
        raise ValueError("bbox must be 3 positive numbers [length, width, height]")
    if all(isinstance(v, int) for v in bbox):
        return list(bbox)
    return [int(v / max(bbox) * 100) for v in bbox]


def submitJob(client, imagePath, bbox=None, minBalance=1.0):
    path = Path(imagePath)
    if not path.is_file() or path.suffix.lower() not in imageTypes:
        raise BlenderError(f"not a usable image: {path}")
    status = ensureReady(client, minBalance)
    images = [[path.suffix.lower(), base64.b64encode(path.read_bytes()).decode("ascii")]]
    params = {"text_prompt": None, "images": images, "bbox_condition": normalizeBbox(bbox)}
    try:
        r = client.send("create_rodin_job", params, timeout=180)
    except BlenderError as e:
        raise explainFailure(client, f"Rodin submit failed: {e}", minBalance) from e
    subscriptionKey = (r.get("jobs") or {}).get("subscription_key")
    if not r.get("uuid") or not subscriptionKey:
        raise explainFailure(client, f"Rodin submit rejected: {r}", minBalance)
    return {"taskUuid": r["uuid"], "subscriptionKey": subscriptionKey, "balanceBefore": status["balance"]}


def pollJob(client, subscriptionKey, pollInterval=5, timeout=600, onProgress=None, maxErrors=3, minBalance=1.0):
    deadline = time.monotonic() + timeout
    errors = 0
    while True:
        try:
            statuses = client.send("poll_rodin_job_status", {"subscription_key": subscriptionKey}, timeout=60)["status_list"]
            errors = 0
        except (BlenderError, KeyError) as e:
            errors += 1
            if errors >= maxErrors:
                raise BlenderError(f"polling failed {errors}x: {e}") from e
            statuses = None
        if statuses is not None:
            if onProgress:
                onProgress(statuses)
            if any(s in ("Failed", "Canceled") for s in statuses):
                raise explainFailure(client, f"Rodin job failed: {statuses}", minBalance)
            if statuses and all(s == "Done" for s in statuses):
                return statuses
        if time.monotonic() > deadline:
            raise BlenderError(f"Rodin job not done after {timeout}s: {statuses}")
        time.sleep(pollInterval)


def importAsset(client, taskUuid, name, retries=3, retryDelay=5):
    for attempt in range(retries):
        try:
            return client.send("import_generated_asset", {"task_uuid": taskUuid, "name": name}, timeout=300)
        except BlenderError as e:
            if attempt == retries - 1:
                raise BlenderError(f"import failed for task {taskUuid}: {e}") from e
            time.sleep(retryDelay)


def generateModel(client, imagePath, name="Product", bbox=None, pollInterval=5, timeout=600, onProgress=None, minBalance=1.0):
    job = submitJob(client, imagePath, bbox, minBalance)
    if onProgress:
        onProgress({"submitted": job["taskUuid"], "balance": job["balanceBefore"]})
    pollJob(client, job["subscriptionKey"], pollInterval, timeout, onProgress, minBalance=minBalance)
    asset = importAsset(client, job["taskUuid"], name)
    try:
        after = checkBalance(client)["balance"]
    except BlenderError:
        after = None
    before = job["balanceBefore"]
    cost = round(before - after, 3) if before is not None and after is not None else None
    return {**job, **asset, "balanceAfter": after, "cost": cost}
