import numpy as np
from PIL import Image, ImageDraw, ImageFilter

paper = (246, 244, 240)
paperShade = (222, 218, 212)
ink = (24, 24, 28)
inkMuted = (78, 78, 86)
neutralAccent = (32, 32, 36)


def loadProduct(path):
    img = Image.open(path)
    img.load()
    img = img.convert("RGBA")
    return img, int(np.asarray(img)[..., 3].min()) < 250


def trimToAlpha(img, threshold=8):
    ys, xs = np.nonzero(np.asarray(img)[..., 3] > threshold)
    if not len(xs):
        raise ValueError("product image is fully transparent")
    return img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def luminance(c):
    r, g, b = (v / 255 for v in c[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readableOn(c):
    return (255, 255, 255) if luminance(c) < 0.55 else ink


def accentColor(img, sample=40000):
    """Dominant vivid hue of the opaque product pixels; near-black for neutral products."""
    px = np.asarray(img.convert("RGBA")).reshape(-1, 4)
    px = px[px[:, 3] > 200][:, :3]
    if len(px) > sample:
        px = px[:: len(px) // sample]
    if not len(px):
        return neutralAccent
    hsv = np.asarray(Image.fromarray(px[None].astype(np.uint8), "RGB").convert("HSV"))[0].astype(int)
    vivid = (hsv[:, 1] > 80) & (hsv[:, 2] > 60) & (hsv[:, 2] < 245)
    if vivid.sum() < 0.03 * len(px):
        return neutralAccent
    bins = hsv[vivid, 0] // 16
    c = px[vivid][bins == np.bincount(bins, minlength=16).argmax()].mean(0)
    while luminance(c) > 0.45:  # keep white CTA text readable
        c = c * 0.85
    return tuple(int(v) for v in c)


def resolveTheme(product=None, theme=None):
    accent = tuple((theme or {}).get("accent") or (accentColor(product) if product is not None else neutralAccent))
    base = {
        "bgTop": mix(paper, accent, 0.06), "bgBottom": mix(paperShade, accent, 0.16),
        "text": ink, "muted": inkMuted, "accent": accent, "ctaText": readableOn(accent),
    }
    return {**base, **{k: tuple(v) for k, v in (theme or {}).items()}}


def gradientBackground(size, theme, glowAt=None):
    w, h = size
    t = np.linspace(0, 1, h)[:, None, None]
    img = np.asarray(theme["bgTop"], float) * (1 - t) + np.asarray(theme["bgBottom"], float) * t
    img = np.broadcast_to(img, (h, w, 3)).copy()
    if glowAt:
        yy, xx = np.mgrid[0:h, 0:w]
        d = np.hypot(xx - glowAt[0], yy - glowAt[1]) / (0.6 * max(w, h))
        img += (255 - img) * (0.35 * np.clip(1 - d, 0, 1) ** 2)[..., None]
    return Image.fromarray(img.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")


def coverFit(img, size):
    w, h = size
    s = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h)).convert("RGBA")


def placeProduct(canvas, product, box, shadow=True):
    """Fit product into box, bottom-aligned so it sits on a soft contact shadow."""
    bx, by, bw, bh = box
    s = min(bw / product.width, bh * 0.94 / product.height)
    p = product.resize((max(1, round(product.width * s)), max(1, round(product.height * s))), Image.LANCZOS)
    x = bx + (bw - p.width) // 2
    y = by + bh - p.height - round(bh * 0.04)
    if shadow:
        sw, sh = p.width * 0.78, max(6, p.width * 0.07)
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        cx, cy = x + p.width / 2, y + p.height - sh * 0.15
        ImageDraw.Draw(layer).ellipse((cx - sw / 2, cy - sh / 2, cx + sw / 2, cy + sh / 2), fill=(0, 0, 0, 90))
        canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(sh * 0.7)))
    canvas.alpha_composite(p, (x, y))
    return (x, y, x + p.width, y + p.height)


def scrim(canvas, rect, opacity=0.5, pad=40):
    x0, y0, x1, y1 = rect
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), radius=pad,
                                            fill=(0, 0, 0, round(255 * opacity)))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(pad / 2)))
