import argparse
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image, ImageDraw  # noqa: E402

from compose import AdCopy, composeAll, formats  # noqa: E402
from e2eTest import check, step  # noqa: E402

copy = AdCopy(title="Aurora Wireless", tagline="Silence the city. Keep the music.",
              specs=["Active noise cancelling", "40-hour battery", "USB-C fast charge"], cta="Shop Now", price="$129")
longCopy = AdCopy(title="The Extraordinarily Comfortable Over-Ear Studio Reference Headphones Edition",
                  tagline="An unreasonably long tagline that will never fit on one line no matter how small the font gets",
                  specs=["Hybrid active noise cancelling with transparency mode and wind reduction"] * 4,
                  cta="Add to cart and checkout today")


def syntheticProduct(path, alpha=True):
    img = Image.new("RGBA" if alpha else "RGB", (700, 900), (0, 0, 0, 0) if alpha else (180, 190, 200))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((150, 120, 550, 860), radius=60, fill=(200, 40, 50, 255))
    d.ellipse((230, 200, 470, 440), fill=(240, 240, 240, 255))
    img.save(path)
    return path


def inside(box, outer, tol=6):
    return box[0] >= outer[0] - tol and box[1] >= outer[1] - tol and \
        box[2] <= outer[0] + outer[2] + tol and box[3] <= outer[1] + outer[3] + tol


def verify(results, transparent):
    check(set(results) == set(formats), f"expected {list(formats)}, got {list(results)}")
    for aspect, r in results.items():
        with Image.open(r["path"]) as img:
            check(img.size == formats[aspect], f"{aspect}: size {img.size} != {formats[aspect]}")
        check(r["transparentInput"] == transparent, f"{aspect}: transparentInput {r['transparentInput']}")
        p = r["boxes"]["product"]
        check(p[2] - p[0] > 50 and p[3] - p[1] > 50, f"{aspect}: product box too small {p}")
        for key in ("title", "specs", "cta"):
            check(r["boxes"][key], f"{aspect}: {key} not drawn")
        for key in ("title", "tagline", "specs", "cta"):
            b = r["boxes"][key]
            check(b is None or inside(b, r["safe"]), f"{aspect}: {key} {b} outside safe area {r['safe']}")
        print(f"  {aspect} {r['path']} boxes {r['boxes']}")


def main():
    p = argparse.ArgumentParser(description="Offline compositor checks")
    p.add_argument("--product", help="real RGBA cutout/render (default: out/headphonesCutout.png if present)")
    p.add_argument("--out", default=str(root / "out" / "hero"))
    a = p.parse_args()
    out = Path(a.out)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        rgba = syntheticProduct(tmp / "product.png")
        rgb = syntheticProduct(tmp / "photo.png", alpha=False)
        step("compose synthetic RGBA", lambda: verify(composeAll(rgba, copy, out, "synthetic"), True))
        step("compose long copy (shrink + ellipsize)", lambda: verify(composeAll(rgba, longCopy, out, "long"), True))
        step("compose opaque input (scrim path)", lambda: verify(composeAll(rgb, copy, out, "opaque"), False))
        step("compose empty specs/tagline", lambda: composeAll(rgba, AdCopy(title="Just a title"), out, "minimal"))

    real = Path(a.product) if a.product else root / "out" / "headphonesCutout.png"
    if real.is_file():
        step(f"compose {real.name}", lambda: verify(composeAll(real, copy, out, real.stem), True))
    else:
        print(f"  skipping real product: {real} not found (run e2eTest or removeBg first)")
    print("all compose checks passed")


if __name__ == "__main__":
    main()
