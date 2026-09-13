import bpy
import requests

trialKey = "vibecoding"


def apiKey():
    server = getattr(bpy.types, "blendermcp_server", None)
    if server is not None and hasattr(server, "_get_hyper3d_api_key"):
        return server._get_hyper3d_api_key()
    return getattr(bpy.context.scene, "blendermcp_hyper3d_api_key", "")


def main(a):
    key = apiKey()
    if not key:
        return {"hasKey": False, "keyType": None, "balance": None}
    r = requests.get("https://hyperhuman.deemos.com/api/v2/check_balance",
                     headers={"Authorization": f"Bearer {key}"}, timeout=20)
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:300]}
    return {
        "hasKey": True,
        "keyType": "free_trial" if key == trialKey else "private",
        "httpStatus": r.status_code,
        "balance": body.get("balance") if r.ok else None,
        "error": None if r.ok else body,
    }
