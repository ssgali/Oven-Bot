import numpy as np
from PIL import Image

# thresholds on product pixels (alpha > 127); luma is 0..1
blankCoverage = 0.01
crowdedCoverage = 0.80
tinyCoverage = 0.04
darkLuma = 0.12
clipShare = 0.15
edgeMargin = 0.01


def imageMetrics(path):
    img = Image.open(path)
    img.load()
    rgba = np.asarray(img.convert("RGBA"))
    h, w = rgba.shape[:2]
    alpha = rgba[..., 3]
    transparent = int(alpha.min()) < 250
    mask = alpha > 127 if transparent else np.ones((h, w), bool)
    coverage = float(mask.mean())
    m = {"size": [w, h], "transparent": transparent, "coverage": round(coverage, 4)}
    if coverage < blankCoverage:
        return {**m, "blank": True}
    ys, xs = np.nonzero(mask)
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    luma = (rgba[..., :3] @ np.array([0.2126, 0.7152, 0.0722]))[mask] / 255
    mx, my = edgeMargin * w, edgeMargin * h
    return {
        **m, "blank": False,
        "bbox": [x0, y0, x1, y1],
        "edgeTouch": transparent and (x0 <= mx or y0 <= my or x1 >= w - mx or y1 >= h - my),
        "lumaMean": round(float(luma.mean()), 4),
        "clipHigh": round(float((luma > 0.98).mean()), 4),
        "clipLow": round(float((luma < 0.02).mean()), 4),
    }


def hardGate(m, params):
    """Deterministic verdict for failures obvious from pixels alone; None means ask the VLM.
    Only meaningful for transparent renders (framing and exposure are measured on the product mask)."""
    padding = lambda delta: round(max(1.2, params.get("padding", 1.6) + delta), 1)
    if m["blank"]:
        return "render is blank or product not in frame", {"padding": padding(0.4)}
    if not m["transparent"]:
        return None
    if m["edgeTouch"]:
        return "product touches the frame edge (cropped)", {"padding": padding(0.3)}
    if m["coverage"] > crowdedCoverage:
        return f"product fills {m['coverage']:.0%} of the frame", {"padding": padding(0.3)}
    if m["coverage"] < tinyCoverage:
        return f"product only fills {m['coverage']:.1%} of the frame", {"padding": padding(-0.4)}
    if m["lumaMean"] < darkLuma or m["clipLow"] > clipShare:
        return f"product underexposed (mean luma {m['lumaMean']}, {m['clipLow']:.0%} crushed)", {"lighting": "highKey"}
    if m["clipHigh"] > clipShare:
        return f"product blown out ({m['clipHigh']:.0%} clipped)", {"lighting": "soft"}
    return None


def flattenForViewing(path, maxSize=1024, bg=(128, 128, 128)):
    """VLMs don't see alpha: composite onto mid-gray and downscale."""
    img = Image.open(path)
    img.load()
    img = img.convert("RGBA")
    img.thumbnail((maxSize, maxSize), Image.LANCZOS)
    flat = Image.new("RGBA", img.size, (*bg, 255))
    flat.alpha_composite(img)
    return flat.convert("RGB")
