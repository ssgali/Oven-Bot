from pathlib import Path

from PIL import Image, ImageDraw

from ..heroShot.typography import drawLines, fitParagraph

framePattern = "frame_{:05d}.png"
scrimFill = (0, 0, 0, 120)
textFill = (255, 255, 255, 255)


def overlayBox(position, w, h):
    pad = round(w * 0.06)
    top = {"top": 0.04, "center": 0.42, "bottom": 0.82, "lowerThird": 0.72}[position]
    return (pad, round(h * top), w - 2 * pad, round(h * 0.16))


def activeOverlays(script, frame):
    for shot in script["shots"]:
        for o in shot["textOverlays"]:
            if o["inFrame"] <= frame <= o["outFrame"]:
                yield o


def drawOverlay(img, overlay):
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    box = overlayBox(overlay["position"], w, h)
    f, lines = fitParagraph(draw, overlay["content"], "bold", box, maxSize=round(h * 0.06), minSize=round(h * 0.03),
                            maxLines=2)
    x, y, bw, bh = box
    draw.rounded_rectangle((x, y, x + bw, y + bh), radius=round(h * 0.02), fill=scrimFill)
    drawLines(draw, lines, f, box, fill=textFill, align="center", valign="center")


def compositeFrame(rawPath, script, frame, outPath):
    img = Image.open(rawPath).convert("RGBA")
    for overlay in activeOverlays(script, frame):
        drawOverlay(img, overlay)
    img.save(outPath)


def compositeOverlays(rawFrameDir, script, compositedDir, startFrame=None, endFrame=None):
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
        compositeFrame(raw, script, frame, out)
        written.append(str(out))
    return {"startFrame": lo, "endFrame": hi, "frames": written}
