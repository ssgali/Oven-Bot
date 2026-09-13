# oven_bot
Multi App Agent Hackathon

## Sample output
[docs/sample-ad.mp4](docs/sample-ad.mp4) — a real video ad produced end-to-end by the `video` pipeline (director agent → Blender render → composited text overlays).

## Setup
```
python -m venv .venv
.venv\Scripts\activate          # bash: source .venv/Scripts/activate
pip install -r requirements.txt
```
First background removal downloads the rembg model once (~180 MB, cached in `~/.rembg`).

Blender: install the "MCP for Blender" addon, N-panel → **Connect** (port 9876).

3D model backend: `blender/customModel` calls a self-hosted image → GLB endpoint (POST `{"image": base64(photo)}`, response body is the `.glb`) instead of Hyper3D Rodin. Set `OVEN_MODEL_ENDPOINT` in `.env` to that endpoint's URL. (Hyper3D Rodin is still available as `blender.generateModelHyper3d` / `blender.hyper3d` if you tick **Hyper3D Rodin** in the addon and set a key.)

VLM (render judge + ad copy), pick one:
- **Hugging Face** (default): `hf auth login` or set `HF_TOKEN` (token needs "Inference Providers" permission). Model `OVEN_VLM_MODEL` (default `Qwen/Qwen3.8-27B`), provider `OVEN_VLM_PROVIDER` (default `auto`).
- **Ollama** (offline): `ollama pull qwen3-vl:2b`, then `OVEN_VLM_BACKEND=ollama`. CPU-only laptops: expect tens of seconds per call.
- **metrics**: no model; pixel checks only, copy built from the seller blurb.

## Layout
```
prep/
  removeBg/            photo → transparent PNG (rembg, OpenCV GrabCut fallback)
blender/               stdlib-only client for the blender-mcp addon socket
  client/              BlenderClient: JSON over TCP, execCode, runScript
  customModel/         image → self-hosted GLB endpoint → import (default model backend)
    blenderScripts/    code that runs inside Blender
  hyper3d/             image → Rodin 3D job → poll → import; balance checks (alternate backend)
    blenderScripts/    code that runs inside Blender
  studio/              backdrop, lights, camera framing, render
    blenderScripts/
  preview/             viewport screenshot sanity check
compose/               Pillow only, no Blender
  heroShot/            product PNG + AdCopy → 9:16 / 1:1 / 16:9 hero shots (Poppins, OFL)
agent/                 decisions; only heroLoop touches Blender
  vlm/                 VlmClient: askJson(prompt, pydanticModel, images) over HF or Ollama
  judge/               pixel gate + VLM verdict + policy (proceed / retry / fallback2d)
  copywriter/          photo + seller blurb → AdCopy, no invented numbers
  heroLoop/            render → judge → retry or fallback → compose; writes decisions.json
bot/                   Discord front end: python -m bot
  discordBot/          OvenBot: one thread per job, downloads, posts assets, approval loop
  pipeline/            HeroPipeline (prep → blender → agent → compose), DevPipeline (no Blender)
  feedback/            reviewer reply → approve / reedit / rerender / regenerate_3d, render nudges
  jobs/                ProductJob + JSON JobStore (data/jobs.json)
  intake/              attachment filtering and download
  config/              Settings from .env
tests/
  e2eTest.py  composeTest.py  judgeTest.py  heroTest.py  botTest.py
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
| `renderStill(c, out, engine, samples, transparent)` | PNG, EEVEE (~35s @1080²) or Cycles (GPU if found); `transparent` hides the backdrop (EEVEE) or makes it a shadow catcher (Cycles) so the PNG is a real product cutout |

The free-trial key (`vibecoding`) is shared by all blender-mcp users. When it runs dry you get `HYPER3D FREE-TRIAL BALANCE EXHAUSTED ...` rather than a vague API error; reuse an already imported model with `--skipGen`.

### Hero shots + the agent decision
```python
from agent import runHero

with BlenderClient() as c:
    result = runHero(c, "Product", referencePath="photo.jpg", cutoutPath=cutout,
                     blurb="Wireless earbuds, 30h battery, IPX4", outDir="out/agent", backend="hf")
# result["source"] is "3d" or "2d"; result["heroes"] maps "9:16" / "1:1" / "16:9" to PNGs
```
Each attempt renders a transparent 1600² still, then `judgeRender` decides:
1. **Pixel gate** (free): blank, cropped at the edge, too small or large, under or over exposed → retry with a deterministic fix, no model call.
2. **VLM verdict**: render (flattened on gray) next to the original photo; scores lighting, visibility, meshQuality, fidelity, composition, then `proceed`, `retry` with a new camera/lighting setup it picks, or `fallback2d`.
3. **Policy** (code): meshQuality or fidelity ≤ 2 → `fallback2d` (a camera can't fix geometry); retry budget spent → `fallback2d`; a repeated setup → orbit to an untried azimuth; params clamped to valid ranges; VLM unreachable → pixel-gate result.

`fallback2d` composes the rembg cutout instead of the render. The full reasoning per attempt is in `out/agent/decisions.json`.

| Function | Notes |
|---|---|
| `composeAll(productPng, copy, outDir)` | RGBA input → gradient bg tinted by the product's accent color, contact shadow, auto-fit text; opaque input → cover crop + text scrim. CLI `python -m compose.heroShot product.png --copy copy.json` |
| `judgeRender(render, reference, history, params, attempt, maxAttempts, vlm)` | returns `Verdict` (`action`, `scores`, `issues`, `retry`, `policy`, `judgedBy`) |
| `writeCopy(reference, blurb, vlm)` | `(AdCopy, info)`; drops lines with numbers not in the blurb and specs repeating the title; falls back to blurb-derived copy |

## Discord bot
```
copy .env.example .env      # set DISCORD_TOKEN; limit intake with DISCORD_INPUT_CHANNEL_ID / DISCORD_ALLOWED_GUILD_ID
python -m bot
```
Discord Developer Portal: enable **Message Content Intent**; invite with View Channels, Send Messages, Read Message History, Create Public Threads, Send Messages in Threads, Attach Files. Blender must be running with the addon connected (see Setup).

Post one message with product photos (optionally a `.txt`/`.csv` spec sheet; the message text is the seller blurb). The bot opens a thread and runs `HeroPipeline`:
1. **Source image**: the largest photo; `rembg` cutout (skipped if it already has alpha, dropped if the mask coverage looks wrong).
2. **Model**: `generateModel` under the job id, poll status posted to the thread.
3. **Hero shots**: only this job's product is visible in the scene, then `runHero` (render → judge → retry / 2D fallback → compose). The three PNGs are attached to the thread.

Replies in the thread rerun only what they touch:

| Reply | Route | Reruns |
|---|---|---|
| `approve`, `lgtm` | approve | nothing |
| `the CTA should say Buy Now`, `shorter title` | reedit | copywriter with the request + current copy → compose (needs a VLM backend) |
| `brighter`, `zoom in`, `other side`, `from above` | rerender | camera/lighting nudged from the last setup → judge loop on the existing model; copy kept |
| `the model is wrong`, `use the other image` | regenerate_3d | next image → cutout → Hyper3D → judge loop |
| `use the 3d render` | use_3d | compose from the last render even though the judge rejected it; later rerenders keep using renders |

Every render attempt is posted to the thread (flattened on gray, next to the judge's verdict), so the 3D result is visible even when the ads fall back to the photo cutout. The price comes from a `Price:` line or a currency amount in the message.

Jobs share one Blender scene, so they queue. If the model has vanished (Blender restarted), a rerender regenerates it. A failed revision keeps the previous assets open for review. Files go to `data/<job>/input` and `data/<job>/v<n>/`, job state to `data/jobs.json`; jobs interrupted by a bot restart are reopened (or failed if they have no assets). `OVEN_PIPELINE=dev` swaps in a pipeline that posts the uploads back, to try the Discord flow without Blender. All `OVEN_*` settings are in `.env.example`.

## Test
```
python tests/botTest.py                                  # offline: routing, store, pipeline revisions with a fake Blender
python tests/e2eTest.py --image headphones.jpeg          # full run, uses one Hyper3D generation
python tests/e2eTest.py --skipGen --obj Product          # reuse object already in scene
python tests/composeTest.py                              # offline, writes out/hero/
python tests/judgeTest.py                                # offline gate/policy/copy checks
python tests/judgeTest.py --live --render out/render.png # one real judge + copy call (--backend ollama)
python tests/heroTest.py --obj Product --blurb "Wireless earbuds, 30h battery"   # agent loop in Blender
python tests/heroTest.py --backend metrics --force retry --maxAttempts 2           # loop control, no model
```
Flags: `--noCutout`, `--engine cycles`, `--transparent`, `--aspect 9:16`, `--lighting dramatic`. Outputs go to `out/`.
