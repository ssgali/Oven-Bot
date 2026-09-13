import argparse
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image, ImageDraw  # noqa: E402

from agent import VlmClient, VlmError, judgeRender, writeCopy  # noqa: E402
from agent.copywriter import CopyDraft, fallbackCopy, sanitize  # noqa: E402
from agent.judge import Verdict, VlmVerdict, applyPolicy, clampParams, defaultParams, hardGate, imageMetrics  # noqa: E402
from e2eTest import check, step  # noqa: E402


def shape(path, color, rect=(300, 250, 700, 750), size=(1000, 1000)):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    if color:
        ImageDraw.Draw(img).rounded_rectangle(rect, radius=40, fill=(*color, 255))
    img.save(path)
    return path


def vlmVerdict(action, mesh=4, fidelity=4, retry=None):
    return VlmVerdict.model_validate({
        "scores": {"lighting": 4, "visibility": 4, "meshQuality": mesh, "fidelity": fidelity, "composition": 4},
        "issues": [], "action": action, "retry": retry, "reason": "test"})


class FakeVlm:
    model = "fake"

    def __init__(self, reply):
        self.reply = reply

    def askJson(self, prompt, schema, images=(), system=None, **kw):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def gateCases(tmp):
    cases = {
        "blank": (shape(tmp / "blank.png", None), "padding"),
        "cropped": (shape(tmp / "cropped.png", (120, 130, 140), rect=(0, 200, 600, 800)), "padding"),
        "dark": (shape(tmp / "dark.png", (10, 10, 10)), "lighting"),
        "blown": (shape(tmp / "blown.png", (255, 255, 255)), "lighting"),
        "good": (shape(tmp / "good.png", (120, 130, 140)), None),
    }
    for name, (path, fixKey) in cases.items():
        gate = hardGate(imageMetrics(path), defaultParams)
        check((gate is None) == (fixKey is None), f"{name}: gate {gate}")
        check(fixKey is None or fixKey in gate[1], f"{name}: expected fix on {fixKey}, got {gate}")
        print(f"  {name}: {gate}")
    return cases["good"][0]


def policyCases(good):
    p = clampParams(defaultParams)
    v = applyPolicy(Verdict(action="retry", reason="", judgedBy="vlm", scores=vlmVerdict("retry", mesh=2).scores),
                    p, [], 1, 3)
    check(v.action == "fallback2d" and v.policy, f"low meshQuality should force fallback2d: {v}")

    v = applyPolicy(Verdict(action="retry", reason="", judgedBy="vlm", retry={"azimuth": 90}), p, [], 3, 3)
    check(v.action == "fallback2d" and v.retry is None, f"exhausted budget should force fallback2d: {v}")

    v = applyPolicy(Verdict(action="retry", reason="", judgedBy="vlm", retry=dict(p)), p, [], 1, 3)
    check(v.action == "retry" and v.retry["azimuth"] != p["azimuth"] and v.policy, f"duplicate should move camera: {v}")

    v = applyPolicy(Verdict(action="retry", reason="", judgedBy="vlm",
                            retry={"azimuth": 999, "elevation": -50, "padding": 9, "lighting": "neon"}), p, [], 1, 3)
    check(v.retry == {"azimuth": 180.0, "elevation": -10.0, "rotationZ": 0.0, "lighting": "soft", "padding": 2.5},
          f"clamp failed: {v.retry}")

    v = judgeRender(good)
    check(v.action == "proceed" and v.judgedBy == "metrics", f"no VLM should proceed on metrics: {v}")
    v = judgeRender(good, vlm=FakeVlm(VlmError("offline")))
    check(v.action == "proceed" and "VLM unavailable" in v.reason, f"VLM error should degrade to metrics: {v}")
    retry = {"azimuth": -90, "elevation": 20, "rotationZ": 0, "lighting": "dramatic", "padding": 1.8}
    v = judgeRender(good, vlm=FakeVlm(vlmVerdict("retry", retry=retry)))
    check(v.action == "retry" and v.retry["azimuth"] == -90.0 and v.judgedBy == "vlm", f"VLM retry lost: {v}")
    print(f"  vlm retry → {v.retry}")


def copyCases():
    blurb = "Wireless earbuds, 30h battery with case, IPX4"
    fb = fallbackCopy(blurb)
    check(fb.title == "Wireless earbuds" and fb.specs == ["30h battery with case", "IPX4"], f"fallback copy: {fb}")
    long = fallbackCopy("Wireless earbuds with charging case, 30h total battery")
    check(long.title == "Wireless earbuds" and long.specs[0] == "Charging case", f"long fallback title: {long}")
    check(fallbackCopy("An extraordinarily long product name without splits").title.endswith("…"), "long title cap")
    draft = CopyDraft(title="Pulse Buds 2", tagline="All-day sound", specs=["30h battery", "50h standby", "IPX4"],
                      cta="Shop Now")
    copy, dropped = sanitize(draft, blurb, fb)
    check(copy.title == "Wireless earbuds" and "50h standby" not in copy.specs and "30h battery" in copy.specs,
          f"invented numbers not removed: {copy}")
    print(f"  sanitized {copy} dropped {dropped}")


def live(a):
    vlm = VlmClient(a.backend, a.model)
    print(f"  {vlm!r}")
    copy, info = writeCopy(a.reference, a.blurb, vlm)
    print(f"  copy {copy} {info}")
    check(info["source"] == "vlm", f"copywriter fell back: {info}")
    v = judgeRender(a.render, a.reference, vlm=vlm)
    print(v.model_dump_json(indent=2))
    check(v.judgedBy == "vlm" or v.metrics.get("blank") is not None, f"judge never reached the VLM: {v.reason}")


def main():
    p = argparse.ArgumentParser(description="Render judge: offline gate/policy checks, or --live against a VLM")
    p.add_argument("--live", action="store_true")
    p.add_argument("--render", default=str(root / "out" / "render.png"))
    p.add_argument("--reference", default=str(root / "headphones.jpeg"))
    p.add_argument("--blurb", default="Wireless earbuds with charging case")
    p.add_argument("--backend", choices=["hf", "ollama"], default="hf")
    p.add_argument("--model")
    a = p.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        good = step("pixel gate", lambda: gateCases(Path(tmp)))
        step("decision policy", lambda: policyCases(good))
    step("copy guardrails", copyCases)
    if a.live:
        step(f"live {a.backend} judge + copy", lambda: live(a))
    print("all judge checks passed")


if __name__ == "__main__":
    main()
