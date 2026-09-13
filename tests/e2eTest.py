import argparse
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8")

from blender import BlenderClient, ensureReady, renderStill, setupStudio, viewportScreenshot  # noqa: E402
from blender import generateModelHyper3d as generateModel  # noqa: E402 (this script exercises Hyper3D specifically)
from prep import hasAlpha, removeBackground  # noqa: E402

assetsDir = root / "tests" / "assets"


def step(name, fn):
    t = time.monotonic()
    print(f"→ {name}", flush=True)
    try:
        result = fn()
    except Exception as e:
        print(f"✘ {name} ({time.monotonic() - t:.1f}s): {e}", flush=True)
        sys.exit(1)
    print(f"✔ {name} ({time.monotonic() - t:.1f}s)", flush=True)
    return result


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def findImage(given):
    if given:
        return Path(given).resolve()
    images = sorted(p for p in assetsDir.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"))
    check(images, f"no image in {assetsDir}; pass --image")
    return images[0]


def main():
    p = argparse.ArgumentParser(description="End-to-end: image → Hyper3D → studio → preview → render")
    p.add_argument("--image")
    p.add_argument("--name", default="Product")
    p.add_argument("--noCutout", action="store_true", help="send image as-is even without transparency")
    p.add_argument("--skipGen", action="store_true", help="reuse --obj already in the scene instead of generating")
    p.add_argument("--obj", default="Product")
    p.add_argument("--engine", choices=["eevee", "cycles"], default="eevee")
    p.add_argument("--transparent", action="store_true")
    p.add_argument("--aspect", default="1:1")
    p.add_argument("--lighting", default="soft")
    p.add_argument("--out", default=str(root / "out"))
    a = p.parse_args()
    out = Path(a.out)

    with BlenderClient() as client:
        def connect():
            check(client.ping().get("pong"), "ping failed")
            info = client.addonInfo()
            print(f"  Blender {info['blender_version']}, addon {info['addon_version']}, protocol {info['protocol_version']}")

        step("connect", connect)

        if a.skipGen:
            objName = a.obj
        else:
            image = step("find image", lambda: findImage(a.image))
            print(f"  {image} ({image.stat().st_size // 1024} KB)")

            if not a.noCutout and not hasAlpha(image):
                def cutout():
                    r = removeBackground(image, out / f"{image.stem}Cutout.png", previewPath=out / f"{image.stem}CutoutPreview.jpg")
                    check(0.02 < r["coverage"] < 0.95, f"cutout coverage {r['coverage']} looks wrong; check {r['outPath']}")
                    print(f"  {r}")
                    return Path(r["outPath"])

                image = step("remove background", cutout)

            def hyper3d():
                s = ensureReady(client)
                print(f"  {s['message']} Balance: {s['balance']}" + (f" (balance check failed: {s['balanceError']})" if s["balanceError"] else ""))

            step("hyper3d status", hyper3d)
            asset = step("generate + import model", lambda: generateModel(
                client, image, a.name, onProgress=lambda s: print(f"  {s}", flush=True)))
            print(f"  task {asset['taskUuid']} → {asset['name']} bbox {asset.get('world_bounding_box')}")
            print(f"  balance {asset['balanceBefore']} → {asset['balanceAfter']} (cost {asset['cost']})")
            objName = asset["name"]

        step("object in scene", lambda: check(client.objectInfo(objName).get("name") == objName, f"{objName} missing"))

        def studio():
            r = setupStudio(client, objName, lighting=a.lighting, aspect=a.aspect)
            names = {o["name"] for o in client.sceneInfo()["objects"]}
            check(set(r["created"]) <= names, f"studio objects missing: {set(r['created']) - names}")
            print(f"  camera {r['camera']} bounds {r['bounds']}")

        step("setup studio", studio)

        def preview():
            r = viewportScreenshot(client, out / "preview.png")
            check(not r["suspectBlank"], f"preview looks blank ({r['bytes']} bytes)")
            print(f"  {r['path']} {r['width']}x{r['height']} via {r['method']}")

        step("viewport screenshot", preview)

        def render():
            r = renderStill(client, out / "render.png", engine=a.engine, transparent=a.transparent)
            print(f"  {r['outPath']} {r['resolution']} {r['engine']}/{r['device']} in {r['seconds']}s")

        step("render", render)

    print("all steps passed")


if __name__ == "__main__":
    main()
