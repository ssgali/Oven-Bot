import re
import textwrap

from pydantic import BaseModel, ConfigDict

from compose import AdCopy
from ..vlm import VlmError

limits = {"title": 32, "tagline": 60, "spec": 36, "cta": 18}
number = re.compile(r"\d+(?:[.,]\d+)?")

copySystem = ("You write short, factual e-commerce ad copy. You never invent specifications, numbers, "
              "certifications or brand names that the seller did not provide.")


class CopyDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    tagline: str
    specs: list[str]
    cta: str


def shorten(text, limit):
    return textwrap.shorten(" ".join(str(text).split()), width=limit, placeholder="…")


def copyPrompt(blurb, productName):
    return f"""Write ad copy for the product in the photo.

Seller notes (the ONLY allowed source of numbers, specs and claims beyond what is visible):
\"\"\"{blurb.strip() or "none"}\"\"\"
Product name: {productName or "not given; use a plain descriptor such as 'Wireless Earbuds'"}

Rules:
- title: at most {limits['title']} characters, the product name or a crisp descriptor
- tagline: at most {limits['tagline']} characters, one benefit-led line
- specs: 2 to 4 items, each at most {limits['spec']} characters, only facts from the seller notes or clearly visible in the photo (color, form factor, visible features). Never invent numbers.
- cta: at most {limits['cta']} characters, e.g. "Shop Now"

Reply with only a JSON object: {{"title": "...", "tagline": "...", "specs": ["..."], "cta": "..."}}"""


def fallbackCopy(blurb="", productName=""):
    parts = [p.strip() for p in re.split(r"[,;\n]|\.\s", blurb) if p.strip()]
    title = productName or (parts.pop(0) if parts else "New Arrival")
    split = len(title) > limits["title"] and re.match(r"(.+?)\s+(with|for)\s+(.+)", title)
    if split:  # "Wireless earbuds with charging case" → title "Wireless earbuds" + spec "Charging case"
        title, word, rest = split.groups()
        parts.insert(0, rest[:1].upper() + rest[1:] if word == "with" else f"For {rest}")
    return AdCopy(title=shorten(title, limits["title"]), specs=[shorten(p, limits["spec"]) for p in parts[:4]])


def sanitize(draft, blurb, fallback):
    """Enforce length caps and drop anything carrying a number the seller never gave."""
    allowed = set(number.findall(blurb))
    invented = lambda s: any(n not in allowed for n in number.findall(s))
    title = shorten(fallback.title if invented(draft.title) or not draft.title.strip() else draft.title,
                    limits["title"])
    repeatsTitle = lambda s: s.strip().lower().startswith(title.lower())
    dropped = [s for s in (draft.title, draft.tagline, *draft.specs) if invented(s)] + \
              [s for s in draft.specs if repeatsTitle(s)]
    copy = AdCopy(
        title=title,
        tagline="" if invented(draft.tagline) else shorten(draft.tagline, limits["tagline"]),
        specs=[shorten(s, limits["spec"]) for s in draft.specs
               if s.strip() and not invented(s) and not repeatsTitle(s)][:4],
        cta=shorten(draft.cta, limits["cta"]) or "Shop Now",
    )
    return copy, dropped


def writeCopy(referencePath=None, blurb="", vlm=None, productName=""):
    """Returns (AdCopy, info). Never raises for model trouble: falls back to copy built from the blurb."""
    fallback = fallbackCopy(blurb, productName)
    if vlm is None:
        return fallback, {"source": "fallback", "reason": "no VLM configured"}
    try:
        draft = vlm.askJson(copyPrompt(blurb, productName), CopyDraft, [referencePath] if referencePath else [],
                            copySystem, maxTokens=1200, temperature=0.6)
    except VlmError as e:
        return fallback, {"source": "fallback", "reason": str(e)}
    copy, dropped = sanitize(draft, blurb, fallback)
    return copy, {"source": "vlm", "model": vlm.model, "dropped": dropped}
