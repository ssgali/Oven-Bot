from pathlib import Path

from PIL import ImageFont

fontsDir = Path(__file__).parent / "fonts"
systemDirs = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"), Path("/Library/Fonts"),
              Path("/System/Library/Fonts/Supplemental")]
fontFiles = {
    "bold": ["Poppins-Bold.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"],
    "semibold": ["Poppins-SemiBold.ttf", "seguisb.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"],
    "regular": ["Poppins-Regular.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "Arial.ttf"],
}
lineGap = 1.18
fonts = {}


def fontPath(weight):
    return next((d / n for n in fontFiles[weight] for d in (fontsDir, *systemDirs) if (d / n).is_file()), None)


def font(weight, size):
    if (weight, size) not in fonts:
        p = fontPath(weight)
        fonts[weight, size] = ImageFont.truetype(str(p), size) if p else ImageFont.load_default(size)
    return fonts[weight, size]


def width(draw, text, f):
    return draw.textlength(text, font=f)


def ellipsize(draw, text, f, maxWidth):
    if width(draw, text, f) <= maxWidth:
        return text
    while text and width(draw, text.rstrip() + "…", f) > maxWidth:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(draw, text, f, maxWidth):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and width(draw, trial, f) > maxWidth:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines


def fitParagraph(draw, text, weight, box, maxSize, minSize, maxLines, fewestLines=False):
    """Largest size where wrapped text fits the box; at minSize, overflow is ellipsized.
    fewestLines prefers fewer lines over a bigger size (avoids one-word orphans in inline lists)."""
    _, _, w, h = box
    for limit in (range(1, maxLines + 1) if fewestLines else [maxLines]):
        for size in range(maxSize, minSize - 1, -2):
            f = font(weight, size)
            lines = wrap(draw, text, f, w)
            if len(lines) <= limit and len(lines) * size * lineGap <= h and all(width(draw, l, f) <= w for l in lines):
                return f, lines
    f = font(weight, minSize)
    lines = wrap(draw, text, f, w)
    n = max(1, min(maxLines, int(h // (minSize * lineGap))))
    if len(lines) > n:
        lines = lines[:n - 1] + [lines[n - 1] + " " + " ".join(lines[n:])]
    return f, [ellipsize(draw, l, f, w) for l in lines]


def fitLines(draw, lines, weight, box, maxSize, minSize):
    """One entry per line (spec bullets): shrink until all fit, then ellipsize the long ones."""
    _, _, w, h = box
    size = max(minSize, min(maxSize, int(h / (max(1, len(lines)) * lineGap))))
    while size > minSize and any(width(draw, l, font(weight, size)) > w for l in lines):
        size -= 2
    f = font(weight, size)
    return f, [ellipsize(draw, l, f, w) for l in lines[:max(1, int(h // (size * lineGap)))]]


def drawLines(draw, lines, f, box, fill, align="center", valign="top"):
    """align: left | center | block (lines left-aligned, block centered). Returns covered bbox or None."""
    if not lines:
        return None
    x, y, w, h = box
    step = f.size * lineGap
    top = y + (h - step * len(lines)) / 2 if valign == "center" else y
    if align == "block":
        anchor, ax = "la", x + (w - max(width(draw, l, f) for l in lines)) / 2
    else:
        anchor, ax = ("ma", x + w / 2) if align == "center" else ("la", x)
    covered = None
    for i, line in enumerate(lines):
        pos = (ax, top + i * step)
        draw.text(pos, line, font=f, fill=fill, anchor=anchor)
        b = draw.textbbox(pos, line, font=f, anchor=anchor)
        covered = b if covered is None else (min(covered[0], b[0]), min(covered[1], b[1]),
                                             max(covered[2], b[2]), max(covered[3], b[3]))
    return covered


def drawPill(draw, text, box, fill, textFill, align="center", minWidthRatio=0.45):
    x, y, w, h = box
    f = font("semibold", max(14, round(h * 0.42)))
    padX = h * 0.6
    label = ellipsize(draw, text, f, w - 2 * padX)
    pw = min(w, max(width(draw, label, f) + 2 * padX, w * minWidthRatio))
    px = x + (w - pw) / 2 if align == "center" else x
    rect = (round(px), y, round(px + pw), y + h)
    draw.rounded_rectangle(rect, radius=h // 2, fill=fill)
    draw.text((px + pw / 2, y + h / 2), label, font=f, fill=textFill, anchor="mm")
    return rect
