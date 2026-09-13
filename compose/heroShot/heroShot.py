from pathlib import Path

from PIL import Image, ImageDraw

from .adCopy import AdCopy
from .backdrop import coverFit, gradientBackground, loadProduct, placeProduct, resolveTheme, scrim, trimToAlpha
from .layout import formats, layouts, scaleBox
from .typography import drawLines, drawPill, fitLines, fitParagraph


def union(rects):
    rects = [r for r in rects if r]
    return (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects))


def drawText(canvas, copy, layout, theme, onPhoto):
    size = canvas.size
    align = layout["align"]
    text, muted = ((255, 255, 255), (230, 230, 230)) if onPhoto else (theme["text"], theme["muted"])
    ctaBox = scaleBox(layout["cta"], size)

    def paragraph(key, value, weight, fill, overlay):
        spec = layout[key]
        box = scaleBox(spec, size)
        f, lines = fitParagraph(ImageDraw.Draw(canvas), value, weight, box, *spec[4:])
        return drawLines(overlay, lines, f, box, fill, align)

    def specs(overlay):
        if not copy.specs:
            return None
        spec = layout["specs"]
        box = scaleBox(spec, size)
        if layout["specStyle"] == "inline":
            f, lines = fitParagraph(overlay, "  ·  ".join(copy.specs), "regular", box, *spec[4:], fewestLines=True)
            return drawLines(overlay, lines, f, box, muted, align)
        f, lines = fitLines(overlay, [f"•  {s}" for s in copy.specs], "regular", box, *spec[4:6])
        return drawLines(overlay, lines, f, box, muted, "block" if align == "center" else align)

    # on a photo the accent pill would vanish into the dark scrim, so invert it
    pillFill, pillText = ((255, 255, 255), theme["text"]) if onPhoto else (theme["accent"], theme["ctaText"])

    def drawAll(overlay):
        return {
            "title": paragraph("title", copy.title, "bold", text, overlay),
            "tagline": paragraph("tagline", copy.tagline, "regular", muted, overlay) if copy.tagline else None,
            "specs": specs(overlay),
            "cta": drawPill(overlay, f"{copy.cta}  ·  {copy.price}" if copy.price else copy.cta, ctaBox,
                            pillFill, pillText, align),
        }

    if onPhoto:
        # measure on a throwaway layer, darken behind the text, then draw for real
        probe = Image.new("RGBA", size)
        scrim(canvas, union(drawAll(ImageDraw.Draw(probe)).values()))
    return drawAll(ImageDraw.Draw(canvas))


def composeHero(productPath, copy, aspect, outPath, theme=None):
    if aspect not in formats:
        raise ValueError(f"aspect must be one of {list(formats)}")
    copy = copy if isinstance(copy, AdCopy) else AdCopy.fromDict(copy)
    size, layout = formats[aspect], layouts[aspect]
    product, transparent = loadProduct(productPath)

    if transparent:
        product = trimToAlpha(product)
        theme = resolveTheme(product, theme)
        px, py, pw, ph = scaleBox(layout["product"], size)
        canvas = gradientBackground(size, theme, glowAt=(px + pw / 2, py + ph / 2))
        boxes = {"product": placeProduct(canvas, product, (px, py, pw, ph))}
    else:
        theme = resolveTheme(None, theme)
        canvas = coverFit(product, size)
        boxes = {"product": (0, 0, *size)}
    boxes.update(drawText(canvas, copy, layout, theme, onPhoto=not transparent))

    outPath = Path(outPath)
    outPath.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(outPath, optimize=True)
    return {
        "path": str(outPath), "aspect": aspect, "size": list(size), "transparentInput": transparent,
        "theme": {k: list(v) for k, v in theme.items()},
        "boxes": {k: [int(v) for v in b] if b else None for k, b in boxes.items()},
        "safe": list(scaleBox(layout["safe"], size)),
    }


def composeAll(productPath, copy, outDir, stem="hero", theme=None, aspects=tuple(formats)):
    if theme is None:
        product, transparent = loadProduct(productPath)
        theme = resolveTheme(trimToAlpha(product) if transparent else None)
    return {a: composeHero(productPath, copy, a, Path(outDir) / f"{stem}_{a.replace(':', 'x')}.png", theme)
            for a in aspects}
