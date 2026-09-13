from __future__ import annotations

from .models import FeedbackAction


def classify_feedback(text: str) -> FeedbackAction:
    normalized = " ".join(text.lower().split())
    if any(word in normalized.split() for word in ("approve", "approved", "lgtm")):
        return FeedbackAction.APPROVE
    if any(term in normalized for term in ("model is wrong", "wrong shape", "regenerate", "use the other image")):
        return FeedbackAction.REGENERATE_3D
    if any(term in normalized for term in ("cta", "text", "copy", "layout", "too small")):
        return FeedbackAction.REEDIT
    if any(term in normalized for term in ("brighter", "darker", "angle", "lighting", "camera", "render")):
        return FeedbackAction.RERENDER
    return FeedbackAction.UNKNOWN
