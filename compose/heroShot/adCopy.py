import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

maxSpecs = 4


@dataclass
class AdCopy:
    title: str = "New Arrival"
    tagline: str = ""
    specs: list[str] = field(default_factory=list)
    cta: str = "Shop Now"
    price: str = ""

    @classmethod
    def fromDict(cls, d):
        clean = lambda v: " ".join(str(v or "").split())
        return cls(
            title=clean(d.get("title")) or "New Arrival",
            tagline=clean(d.get("tagline")),
            specs=[s for s in map(clean, d.get("specs") or []) if s][:maxSpecs],
            cta=clean(d.get("cta")) or "Shop Now",
            price=clean(d.get("price")),
        )

    @classmethod
    def fromJson(cls, path):
        return cls.fromDict(json.loads(Path(path).read_text(encoding="utf-8")))

    def toDict(self):
        return asdict(self)
