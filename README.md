# oven_bot
Multi App Agent Hackathon

## Setup
```
python -m venv .venv
.venv\Scripts\activate          # bash: source .venv/Scripts/activate
pip install -r requirements.txt
```
First background removal downloads the rembg model once (~180 MB, cached in `~/.rembg`).

Blender: install the "MCP for Blender" addon, N-panel → **Connect** (port 9876), tick **Hyper3D Rodin**, mode **hyper3d.ai**, set a key.

## Layout
```
prep/
  removeBg/            photo → transparent PNG (rembg, OpenCV GrabCut fallback)
blender/               stdlib-only client for the blender-mcp addon socket
  client/              BlenderClient: JSON over TCP, execCode, runScript
  hyper3d/             image → Rodin 3D job → poll → import; balance checks
    blenderScripts/    code that runs inside Blender
  studio/              backdrop, lights, camera framing, render
    blenderScripts/
  preview/             viewport screenshot sanity check
tests/
  e2eTest.py
```
`blenderScripts/*.py` run inside Blender via `client.runScript(path, args)`: the script gets `args`, defines `main(args)`, and its return value comes back as JSON.

## Pipeline
```python
from blender import BlenderClient, generateModel, setupStudio, viewportScreenshot, renderStill
from prep import removeBackground

cutout = removeBackground("photo.jpg", "out/cutout.png")["outPath"]
with BlenderClient() as c:
    asset = generateModel(c, cutout, "Product")               # balance check → submit → poll → import
    setupStudio(c, asset["name"], lighting="soft", aspect="4:5")
    viewportScreenshot(c, "out/preview.png")                  # cheap check before rendering
    renderStill(c, "out/render.png", engine="eevee")          # or "cycles", transparent=True
```

| Function | Notes |
|---|---|
| `removeBackground(in, out, method="rembg")` | `method="grabcut"` works offline without the model; CLI `python prep/removeBg/removeBg.py photo.jpg --preview out/p.jpg` |
| `BlenderClient.send(type, params, timeout)` | raises `BlenderError` on `status:error`, `result.error`, `succeed:false` |
| `hyper3dStatus(c)` / `ensureReady(c)` | enabled, mode, key type, live balance; `ensureReady` raises `Hyper3dBalanceError` when credits are gone |
| `submitJob` / `pollJob` / `importAsset` | split steps, to resume a job without paying again; failures recheck balance |
| `setupStudio(c, objName, ...)` | removes default Cube/Light/Camera + previous studio objects, scales product to `targetSize`, curved backdrop, key/fill/rim (`soft`, `dramatic`, `highKey`), camera fit to bbox (`azimuth`, `elevation`, `lens`, `padding`), `aspect` `1:1`/`4:5`/`9:16`/`16:9` |
| `viewportScreenshot(c, out)` | camera view, material preview, overlays off; flags near-empty images |
| `renderStill(c, out, engine, samples, transparent)` | PNG, EEVEE (~35s @1080²) or Cycles (GPU if found) |

The free-trial key (`vibecoding`) is shared by all blender-mcp users. When it runs dry you get `HYPER3D FREE-TRIAL BALANCE EXHAUSTED ...` rather than a vague API error; reuse an already imported model with `--skipGen`.

## Test
```
python tests/e2eTest.py --image headphones.jpeg          # full run, uses one Hyper3D generation
python tests/e2eTest.py --skipGen --obj Product          # reuse object already in scene
```
Flags: `--noCutout`, `--engine cycles`, `--transparent`, `--aspect 9:16`, `--lighting dramatic`. Outputs go to `out/`.
