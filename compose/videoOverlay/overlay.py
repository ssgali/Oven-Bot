from pathlib import Path

from PIL import Image, ImageDraw

from ..heroShot.backdrop import scrim
from ..heroShot.typography import drawLines, fitParagraph

framePattern = "frame_{:05d}.png"
textFill = (255, 255, 255, 255)


def overlayBox(position, w, h):
    pad = round(w * 0.07)
    top = {"top": 0.05, "center": 0.42, "bottom": 0.80, "lowerThird": 0.70}[position]
    return (pad, round(h * top), w - 2 * pad, round(h * 0.18))


def activeOverlays(script, frame):
    for shot in script["shots"]:
        for o in shot["textOverlays"]:
            if o["inFrame"] <= frame <= o["outFrame"]:
                yield o


def drawOverlay(img, overlay, accent=None):
    """A soft blurred scrim hugging the wrapped text (mirrors heroShot's on-photo caption treatment)
    plus, when this job has a resolved brand accent, a thin accent-colored bar under the headline."""
    w, h = img.size
    box = overlayBox(overlay["position"], w, h)
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    f, lines = fitParagraph(measure, overlay["content"], "bold", box, maxSize=round(h * 0.062),
                            minSize=round(h * 0.032), maxLines=2)
    textBox = drawLines(measure, lines, f, box, fill=textFill, align="center", valign="center")
    scrim(img, textBox, opacity=0.55, pad=round(h * 0.03))
    if accent:
        x0, y0, x1, y1 = textBox
        barW, barH = round((x1 - x0) * 0.32), max(3, round(h * 0.007))
        bx, by = x0 + (x1 - x0 - barW) // 2, y1 + round(h * 0.018)
        ImageDraw.Draw(img, "RGBA").rounded_rectangle((bx, by, bx + barW, by + barH), radius=barH // 2,
                                                       fill=(*accent, 255))
    drawLines(ImageDraw.Draw(img, "RGBA"), lines, f, box, fill=textFill, align="center", valign="center")


def compositeFrame(rawPath, script, frame, outPath, accent=None):
    img = Image.open(rawPath).convert("RGBA")
    for overlay in activeOverlays(script, frame):
        drawOverlay(img, overlay, accent)
    img.save(outPath)


def compositeOverlays(rawFrameDir, script, compositedDir, startFrame=None, endFrame=None, accent=None):
    """Redraws text overlays for [startFrame, endFrame] (default: the whole timeline) from existing raw
    renders. No Blender involved — this is what makes a text-only revision cheap."""
    rawFrameDir, compositedDir = Path(rawFrameDir), Path(compositedDir)
    compositedDir.mkdir(parents=True, exist_ok=True)
    lo = 0 if startFrame is None else startFrame
    hi = (script["totalFrames"] - 1) if endFrame is None else endFrame
    written = []
    for frame in range(lo, hi + 1):
        name = framePattern.format(frame)
        raw = rawFrameDir / name
        if not raw.is_file():
            continue
        out = compositedDir / name
        compositeFrame(raw, script, frame, out, accent)
        written.append(str(out))
    return {"startFrame": lo, "endFrame": hi, "frames": written}
