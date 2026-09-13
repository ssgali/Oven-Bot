formats = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}

# Boxes are (x, y, w, h) as fractions of the canvas. Text entries carry (maxSize, minSize, maxLines) in px.
# "safe" is where text may land; 9:16 keeps the top 10% and bottom 15% clear for Reels/TikTok UI.
layouts = {
    "9:16": {
        "align": "center", "specStyle": "bullets",
        "safe": (0.06, 0.10, 0.88, 0.75),
        "product": (0.08, 0.11, 0.84, 0.40),
        "title": (0.08, 0.53, 0.84, 0.08, 96, 48, 2),
        "tagline": (0.08, 0.615, 0.84, 0.04, 46, 28, 1),
        "specs": (0.08, 0.665, 0.84, 0.105, 42, 26, 4),
        "cta": (0.08, 0.785, 0.84, 0.05),
    },
    "1:1": {
        "align": "center", "specStyle": "inline",
        "safe": (0.05, 0.04, 0.90, 0.92),
        "product": (0.12, 0.05, 0.76, 0.50),
        "title": (0.06, 0.57, 0.88, 0.09, 72, 40, 2),
        "tagline": (0.06, 0.665, 0.88, 0.045, 40, 24, 1),
        "specs": (0.06, 0.72, 0.88, 0.115, 34, 22, 2),
        "cta": (0.06, 0.855, 0.88, 0.08),
    },
    "16:9": {
        "align": "left", "specStyle": "bullets",
        "safe": (0.04, 0.06, 0.92, 0.88),
        "product": (0.04, 0.08, 0.50, 0.84),
        "title": (0.58, 0.18, 0.38, 0.17, 88, 48, 3),
        "tagline": (0.58, 0.36, 0.38, 0.08, 44, 26, 2),
        "specs": (0.58, 0.46, 0.38, 0.27, 42, 26, 4),
        "cta": (0.58, 0.77, 0.38, 0.09),
    },
}


def scaleBox(box, size):
    w, h = size
    x, y, bw, bh = box[:4]
    return (round(x * w), round(y * h), round(bw * w), round(bh * h))
