import json

directorSystem = (
    "You direct short vertical product-ad videos. You are given product photo(s) and a spec sheet, and you write "
    "a shot-by-shot script as JSON: camera moves (orbit/elevation/lens/padding), a lighting preset per shot, and "
    "timed text overlays. You never invent specs or numbers the seller did not provide."
)

reviseSystem = (
    "You revise a shot-by-shot video ad script in response to a human reviewer's critique. You have tools to "
    "inspect the current render and to re-render either a scoped range of frames or the whole video. Prefer the "
    "smallest change that satisfies the critique: touch only the shot(s) the critique is actually about, and "
    "prefer recompositing text overlays over a full Blender re-render when only text changed. You must call "
    "propose_revision exactly once, early, to commit to a plan before using any rendering tool, and call "
    "finish_revision only once the result matches the critique."
)


def scriptPrompt(specBlurb, fps, aspect, minSeconds=4, maxSeconds=12):
    return f"""Write a video ad script for the product in the photo(s).

Seller notes (the ONLY allowed source of numbers, specs and claims beyond what is visible):
\"\"\"{specBlurb.strip() or "none"}\"\"\"

Rules:
- {minSeconds}-{maxSeconds} seconds total at {fps} fps, aspect {aspect}.
- 2-4 shots, each a distinct camera angle telling a small story (e.g. establishing angle, a detail/feature shot,
  a hero angle for the final beat). Consecutive shots must be "cut": touching exactly, no gap and no overlap.
- Camera fields per keyframe: azimuth -180..180 (degrees around the product), elevation -10..45, rotationZ
  -180..180 (spins the product), lens 50..135, padding 1.2..2.5 (larger = more empty space). Give each shot
  at least a start and end camera keyframe; a pan is two keyframes with different azimuth/elevation.
- lighting is one of soft | dramatic | highKey per shot (one lighting keyframe at the shot's start frame).
- textOverlays: short, factual, only from the seller notes; give each an id, inFrame/outFrame within its shot,
  and a position (top | center | bottom | lowerThird).
- Frame numbers are absolute, 0-indexed across the whole timeline. totalFrames is a COUNT (fps * seconds),
  so the last valid frame index is totalFrames - 1: the first shot's startFrame is 0 and the last shot's
  endFrame must be exactly totalFrames - 1 (e.g. 8 seconds at 8 fps is totalFrames=64, last endFrame=63).
  Shots must be contiguous: each shot's startFrame equals the previous shot's endFrame.

Reply with only a JSON object matching the schema."""


def revisePrompt(script, critique, history):
    tried = "\n".join(f"- {h['feedback']!r} -> {h['scope']} rerender of {h['shotIds']}" for h in history) or "- none"
    return f"""Current script:
{json.dumps(script, indent=2)}

Reviewer's critique of the last render: {critique!r}

Earlier revisions in this session (do not repeat an already-tried fix for the same complaint):
{tried}

Inspect preview frames of the affected shot(s) if you need to see what the reviewer saw, then call
propose_revision with the smallest script change that addresses the critique."""
