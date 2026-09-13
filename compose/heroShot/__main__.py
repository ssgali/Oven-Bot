import argparse
import json

from .adCopy import AdCopy
from .heroShot import composeAll


def main():
    p = argparse.ArgumentParser(prog="python -m compose.heroShot",
                                description="Product PNG + ad copy → hero shots at 9:16, 1:1, 16:9")
    p.add_argument("product", help="RGBA cutout/render (opaque images get a text scrim instead)")
    p.add_argument("--copy", help="JSON with title, tagline, specs[], cta, price")
    p.add_argument("--title")
    p.add_argument("--cta")
    p.add_argument("-o", "--out", default="out/hero")
    p.add_argument("--stem", default="hero")
    a = p.parse_args()
    copy = AdCopy.fromJson(a.copy) if a.copy else AdCopy()
    copy.title, copy.cta = a.title or copy.title, a.cta or copy.cta
    for aspect, r in composeAll(a.product, copy, a.out, a.stem).items():
        print(aspect, json.dumps({k: r[k] for k in ("path", "boxes")}))


main()
