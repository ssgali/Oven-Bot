import re
from pathlib import Path

from ..client import BlenderError

scriptsDir = Path(__file__).parent / "blenderScripts"


class Hyper3dBalanceError(BlenderError):
    pass


def checkBalance(client):
    return client.runScript(scriptsDir / "checkBalance.py", timeout=60)


def hyper3dStatus(client, withBalance=True):
    r = client.send("get_hyper3d_status")
    msg = " ".join(r.get("message", "").split())
    mode = re.search(r"Mode: (\w+)", msg)
    keyType = re.search(r"Key type: (\w+)", msg)
    status = {
        "enabled": bool(r.get("enabled")),
        "mode": mode and mode.group(1),
        "keyType": keyType and keyType.group(1),
        "balance": None,
        "balanceError": None,
        "message": msg,
    }
    if withBalance and status["enabled"]:
        try:
            b = checkBalance(client)
            status["balance"], status["balanceError"] = b["balance"], b.get("error")
        except BlenderError as e:
            status["balanceError"] = str(e)
    return status


def balanceMessage(status, minBalance):
    if status["keyType"] == "free_trial":
        return (f"HYPER3D FREE-TRIAL BALANCE EXHAUSTED ({status['balance']} left, need {minBalance}). "
                "The trial key is shared by every blender-mcp user and is limited per day. "
                "Fix: wait for it to refill, or paste a private key from hyper3d.ai into the MCP for Blender panel. "
                "To keep working meanwhile, reuse an imported model: e2eTest.py --skipGen --obj <name>.")
    return (f"HYPER3D ACCOUNT BALANCE EXHAUSTED ({status['balance']} left, need {minBalance}). "
            "Fix: top up credits at hyper3d.ai.")


def ensureReady(client, minBalance=1.0):
    s = hyper3dStatus(client)
    if not s["enabled"]:
        raise BlenderError(f"Hyper3D not ready: {s['message']}")
    if s["mode"] != "MAIN_SITE":
        raise BlenderError(f"Hyper3D mode is {s['mode']}; switch to hyper3d.ai (MAIN_SITE), FAL_AI only accepts image URLs")
    if s["balance"] is not None and s["balance"] < minBalance:
        raise Hyper3dBalanceError(balanceMessage(s, minBalance))
    return s


def explainFailure(client, err, minBalance=1.0):
    try:
        s = hyper3dStatus(client)
    except BlenderError:
        return BlenderError(err)
    if s["balance"] is not None and s["balance"] < minBalance:
        return Hyper3dBalanceError(f"{balanceMessage(s, minBalance)} [original error: {err}]")
    return BlenderError(err)
