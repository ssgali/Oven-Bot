import argparse
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image  # noqa: E402

from agent import runHero  # noqa: E402
from agent.judge import Verdict, applyPolicy  # noqa: E402
from blender import BlenderClient  # noqa: E402
from compose import formats  # noqa: E402
from e2eTest import check, step  # noqa: E402
from prep import hasAlpha, removeBackground  # noqa: E402


def forcedJudge(action):
    """Skips the model but still goes through the real policy, so budget/fallback handling is exercised."""
    def judge(renderPath, referencePath, history, params, attempt, maxAttempts, vlm):
        retry = {"azimuth": params["azimuth"] + 90} if action == "retry" else None
        v = Verdict(action=action, reason=f"forced {action} (test)", judgedBy="metrics", retry=retry)
        return applyPolicy(v, params, history, attempt, maxAttempts)
    return judge


def main():
    p = argparse.ArgumentParser(description="Agent loop against Blender: render → judge → retry/fallback → hero shots")
    p.add_argument("--obj", default="Product", help="object already in the scene (run e2eTest first)")
    p.add_argument("--reference", default=str(root / "headphones.jpeg"))
    p.add_argument("--cutout", help="2D fallback image (default: rembg cutout of --reference)")
    p.add_argument("--blurb", default="")
    p.add_argument("--name", default="")
    p.add_argument("--backend", choices=["hf", "ollama", "metrics"], default="hf")
    p.add_argument("--maxAttempts", type=int, default=3)
    p.add_argument("--engine", choices=["eevee", "cycles"], default="eevee")
    p.add_argument("--force", choices=["retry", "fallback2d"], help="replace the judge to test loop control")
    p.add_argument("--out", default=str(root / "out" / "agent"))
    a = p.parse_args()
    out = Path(a.out)

    reference = Path(a.reference)
    cutout = Path(a.cutout) if a.cutout else None
    if cutout is None:
        cutout = reference if hasAlpha(reference) else step(
            "cutout for 2D fallback",
            lambda: Path(removeBackground(reference, out / f"{reference.stem}Cutout.png")["outPath"]))

    with BlenderClient() as client:
        step("connect", lambda: check(client.ping().get("pong"), "ping failed"))
        step("object in scene", lambda: check(client.objectInfo(a.obj).get("name") == a.obj, f"{a.obj} missing"))
        kw = {"judge": forcedJudge(a.force)} if a.force else {}
        trace = step("agent loop", lambda: runHero(
            client, a.obj, reference, cutout, a.blurb, a.name, out, a.maxAttempts, a.backend, a.engine,
            onEvent=lambda s: print(f"  {s}", flush=True), **kw))

    def verify():
        check(Path(out / "decisions.json").is_file(), "decisions.json missing")
        check(len(trace["attempts"]) <= a.maxAttempts, f"{len(trace['attempts'])} attempts > budget")
        for aspect, path in trace["heroes"].items():
            with Image.open(path) as img:
                check(img.size == formats[aspect], f"{aspect}: {img.size}")
        if a.force:
            check(trace["source"] == "2d", f"forced {a.force} should end in the 2D fallback, got {trace['source']}")
        print(f"  source {trace['source']} after {len(trace['attempts'])} attempt(s)")
        print(f"  {json.dumps(trace['heroes'])}")

    step("verify outputs", verify)
    print("agent loop passed")


if __name__ == "__main__":
    main()
