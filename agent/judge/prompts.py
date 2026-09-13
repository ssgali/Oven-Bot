import json

judgeSystem = (
    "You are the quality gate in an automated product-advertising pipeline. A 3D model was generated from a "
    "single product photo and rendered in a virtual studio. You decide whether the render is good enough to "
    "become an ad, whether a different camera/lighting setup would fix it, or whether the 3D model is unusable "
    "and the pipeline should fall back to the flat photo cutout. Be strict: a bad ad is worse than a 2D fallback."
)


def judgePrompt(params, history, hasReference):
    images = "Image 1: the render. The background is flat gray on purpose; ignore it."
    if hasReference:
        images += "\nImage 2: the original product photo the 3D model was generated from."
    tried = "\n".join(f"- attempt {h['attempt']}: {json.dumps(h['params'])} → {h['verdict']['action']}: "
                      f"{'; '.join(h['verdict']['issues']) or h['verdict']['reason']}" for h in history) or "- none"
    return f"""{images}

Score each 1-5 (5 = best):
- lighting: form is readable, no crushed shadows or blown highlights
- visibility: whole product in frame, its most recognizable side faces the camera, not tiny
- meshQuality: no holes, melted/blobby or spiky geometry, smeared or stretched textures, floating fragments
- fidelity: shape, colors and key details match the photo{"" if hasReference else " (no photo given: judge plausibility)"}
- composition: an attractive hero angle for an ad

Then choose action:
- "proceed": ready for an ad (every score >= 3).
- "retry": the problem is fixable with camera or lighting (wrong side facing camera, awkward angle, too dark or bright, cropped, too small). Fill in every retry field.
- "fallback2d": the 3D model itself is broken or does not look like the product; no camera change can fix it.

Current render setup: {json.dumps(params)}
Retry fields: azimuth -180..180 (degrees the camera orbits around the product; +/-90 shows a side, 180 the back),
elevation -10..45 (camera height in degrees), rotationZ -180..180 (spins the product itself),
lighting one of soft | dramatic | highKey, padding 1.2..2.5 (larger = more empty space around the product).

Previous attempts (never propose the same setup again):
{tried}

Reply with only a JSON object: {{"scores": {{"lighting": n, "visibility": n, "meshQuality": n, "fidelity": n, "composition": n}}, "issues": ["..."], "action": "proceed|retry|fallback2d", "retry": {{"azimuth": n, "elevation": n, "rotationZ": n, "lighting": "...", "padding": n}} or null, "reason": "one sentence"}}"""
