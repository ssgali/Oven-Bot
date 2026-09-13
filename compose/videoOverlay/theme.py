import json
from pathlib import Path

from PIL import Image

from ..heroShot.backdrop import accentColor, mix, neutralAccent

# curated, unmistakably vivid picks for products with no vivid color of their own (black/white/gray goods)
vibrantFallbacks = [(230, 126, 34), (52, 152, 219), (155, 89, 182), (26, 188, 156), (231, 76, 60), (241, 196, 15)]


def resolveAccent(imagePath, objName=""):
    """A vivid brand color for this product: its own dominant hue, or (keyed off objName, so repeat runs
    of the same product stay consistent) a curated pick when the product has no vivid color of its own."""
    accent = accentColor(Image.open(imagePath).convert("RGBA"))
    if tuple(accent) == neutralAccent:
        accent = vibrantFallbacks[sum(map(ord, objName)) % len(vibrantFallbacks)]
    return tuple(int(c) for c in accent)


def backdropColor(accent):
    """Studio backdrop material color (0-1 floats): the accent lifted toward white so it reads as a
    colorful seamless backdrop under studio lighting instead of an overpowering wall of saturated color."""
    return tuple(c / 255 for c in mix(accent, (255, 255, 255), 0.35))


def themeFile(versionDir):
    return Path(versionDir) / "theme.json"


def loadOrComputeAccent(versionDir, imagePath=None, objName=""):
    """Resolves once per job and caches to `versionDir`/theme.json, so every later scoped revision keeps
    the same backdrop/accent color instead of it drifting shot to shot."""
    path = themeFile(versionDir)
    if path.is_file():
        return tuple(json.loads(path.read_text())["accent"])
    if imagePath is None:
        raise FileNotFoundError(f"no cached theme at {path} and no image given to compute one")
    accent = resolveAccent(imagePath, objName)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"accent": list(accent)}))
    return accent
