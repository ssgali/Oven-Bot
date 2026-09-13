import argparse
from pathlib import Path

import cv2
import numpy as np

sessions = {}


def readImage(path, flags=cv2.IMREAD_COLOR):
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), flags)
    if img is None:
        raise ValueError(f"cannot read image {path}")
    return img


def hasAlpha(path):
    img = readImage(path, cv2.IMREAD_UNCHANGED)
    return img.ndim == 3 and img.shape[2] == 4 and img[..., 3].min() < 250


def dropSpecks(mask, minRatio=0.02):
    n, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 127).astype(np.uint8), connectivity=8)
    if n <= 1:
        return mask
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = np.isin(labels, 1 + np.nonzero(areas >= areas.max() * minRatio)[0]).astype(np.uint8) * 255
    return np.minimum(mask, cv2.dilate(keep, np.ones((5, 5), np.uint8)))


def fillHoles(mask):
    flood = mask.copy()
    cv2.floodFill(flood, np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), np.uint8), (0, 0), 255)
    return mask | cv2.bitwise_not(flood)


def rembgMask(img, model):
    from rembg import new_session, remove
    if model not in sessions:
        sessions[model] = new_session(model)
    return remove(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), session=sessions[model], only_mask=True)


def autoRect(img):
    h, w = img.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 40, 120), np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    border = max(2, int(0.01 * max(h, w)))
    inner = [b for b in map(cv2.boundingRect, contours)
             if b[0] > border and b[1] > border and b[0] + b[2] < w - border and b[1] + b[3] < h - border]
    if not inner or max(b[2] * b[3] for b in inner) < 0.01 * w * h:
        m = int(0.05 * min(h, w))
        return (m, m, w - 2 * m, h - 2 * m)
    x, y, bw, bh = max(inner, key=lambda b: b[2] * b[3])
    pad = int(0.05 * max(bw, bh))
    x0, y0 = max(1, x - pad), max(1, y - pad)
    return (x0, y0, min(w - 2, x + bw + pad) - x0, min(h - 2, y + bh + pad) - y0)


def grabCut(img, mask=None, rect=None, iterations=5):
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    if rect is not None:
        mask = np.zeros(img.shape[:2], np.uint8)
        cv2.grabCut(img, mask, rect, bgd, fgd, iterations, cv2.GC_INIT_WITH_RECT)
    else:
        cv2.grabCut(img, mask, None, bgd, fgd, iterations, cv2.GC_INIT_WITH_MASK)
    return np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)


def grabCutMask(img, rect=None, workSize=800, iterations=5, feather=1.5):
    h, w = img.shape[:2]
    s = min(1.0, workSize / max(h, w))
    small = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img
    r = tuple(round(v * s) for v in rect) if rect else autoRect(small)
    fg = fillHoles(dropSpecks(grabCut(small, rect=r, iterations=iterations)))
    fg = cv2.resize(fg, (w, h), interpolation=cv2.INTER_NEAREST)
    k = np.ones((max(3, round(8 / s)),) * 2, np.uint8)
    m = np.full((h, w), cv2.GC_BGD, np.uint8)
    m[cv2.dilate(fg, k) > 0] = cv2.GC_PR_BGD
    m[fg > 0] = cv2.GC_PR_FGD
    m[cv2.erode(fg, k) > 0] = cv2.GC_FGD
    fg = fillHoles(dropSpecks(grabCut(img, mask=m, iterations=2)))
    return cv2.GaussianBlur(fg, (0, 0), feather) if feather else fg


def removeBackground(inPath, outPath=None, method="rembg", model="isnet-general-use", rect=None, pad=0.06, previewPath=None):
    inPath = Path(inPath)
    outPath = Path(outPath) if outPath else inPath.with_name(f"{inPath.stem}Cutout.png")
    img = readImage(inPath)
    h, w = img.shape[:2]
    if method == "rembg":
        alpha = dropSpecks(rembgMask(img, model))
    elif method == "grabcut":
        alpha = grabCutMask(img, rect)
    else:
        raise ValueError("method must be 'rembg' or 'grabcut'")

    ys, xs = np.nonzero(alpha > 8)
    if not len(xs):
        raise RuntimeError(f"no foreground found in {inPath}")
    p = int(pad * max(np.ptp(xs), np.ptp(ys)))
    x0, y0 = max(0, xs.min() - p), max(0, ys.min() - p)
    x1, y1 = min(w, xs.max() + p + 1), min(h, ys.max() + p + 1)
    rgba = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    rgba[..., 3] = alpha
    rgba = rgba[y0:y1, x0:x1]
    outPath.parent.mkdir(parents=True, exist_ok=True)
    cv2.imencode(".png", rgba)[1].tofile(str(outPath))

    if previewPath:
        a = rgba[..., 3:4] / 255.0
        checker = (np.indices(rgba.shape[:2]).sum(0) // 24 % 2 * 60 + 150)[..., None]
        comp = (rgba[..., :3] * a + checker * (1 - a)).astype(np.uint8)
        Path(previewPath).parent.mkdir(parents=True, exist_ok=True)
        cv2.imencode(Path(previewPath).suffix or ".jpg", comp)[1].tofile(str(previewPath))

    return {
        "outPath": str(outPath),
        "method": method,
        "crop": [int(x0), int(y0), int(x1 - x0), int(y1 - y0)],
        "coverage": round(float((alpha > 127).mean()), 4),
    }


def main():
    p = argparse.ArgumentParser(description="Remove photo background → transparent PNG")
    p.add_argument("image")
    p.add_argument("-o", "--out")
    p.add_argument("--method", choices=["rembg", "grabcut"], default="rembg")
    p.add_argument("--model", default="isnet-general-use", help="rembg model, e.g. u2net, isnet-general-use, birefnet-general")
    p.add_argument("--rect", help="grabcut only: x,y,w,h around the product (default: auto)")
    p.add_argument("--preview", help="write a checkerboard composite for eyeballing")
    a = p.parse_args()
    rect = tuple(int(v) for v in a.rect.split(",")) if a.rect else None
    print(removeBackground(a.image, a.out, a.method, a.model, rect, previewPath=a.preview))


if __name__ == "__main__":
    main()
