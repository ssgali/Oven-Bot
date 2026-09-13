import re

from agent.judge import clampParams
from ..jobs import FeedbackAction

approveWords = ("approve", "approved", "lgtm")
use3dTerms = ("use the 3d", "use 3d", "use the render", "use the blender", "3d version")
regenerateTerms = ("model is wrong", "wrong model", "wrong shape", "regenerate", "use the other image",
                   "different image", "new model")
reeditTerms = ("cta", "text", "copy", "title", "tagline", "headline", "specs", "price", "wording", "layout", "font")
rerenderTerms = ("brighter", "darker", "too dark", "too bright", "lighting", "light", "shadow", "angle", "camera",
                 "render", "rotate", "closer", "zoom", "further", "side", "higher", "lower", "too small", "too big",
                 "cropped")


def normalize(text):
    return " ".join(text.lower().split())


def mentions(text, terms):
    return any(re.search(rf"\b{re.escape(t)}\b", text) for t in terms)


def classifyFeedback(text):
    """Keyword router; copy terms win over render terms so "the CTA is too small" edits text, not the camera."""
    text = normalize(text)
    for terms, action in ((approveWords, FeedbackAction.APPROVE), (use3dTerms, FeedbackAction.USE_3D),
                          (regenerateTerms, FeedbackAction.REGENERATE_3D),
                          (reeditTerms, FeedbackAction.REEDIT), (rerenderTerms, FeedbackAction.RERENDER)):
        if mentions(text, terms):
            return action
    return FeedbackAction.UNKNOWN


def adjustRenderParams(feedback, params):
    """Nudge the last studio setup the way the reviewer asked; unrecognized requests still get a new view."""
    text = normalize(feedback)
    has = lambda *terms: mentions(text, terms)
    before = clampParams(params)
    p = dict(before)
    if has("brighter", "too dark", "lighter"):
        p["lighting"] = "highKey"
    elif has("darker", "too bright", "dramatic", "moody", "contrast"):
        p["lighting"] = "dramatic"
    elif has("soft", "softer"):
        p["lighting"] = "soft"
    if has("closer", "zoom in", "bigger", "larger", "too small"):
        p["padding"] -= 0.3
    elif has("further", "zoom out", "smaller", "too big", "cropped", "cut off"):
        p["padding"] += 0.3
    if has("from above", "higher", "overhead", "top down"):
        p["elevation"] += 15
    elif has("from below", "lower", "eye level"):
        p["elevation"] -= 10
    if has("other side", "side view", "profile"):
        p["azimuth"] += 90
    elif has("angle", "rotate", "turn") or p == before:
        p["azimuth"] += 45
    p["azimuth"] = (p["azimuth"] + 180) % 360 - 180
    return clampParams(p)
