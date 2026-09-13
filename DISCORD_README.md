# Oven-Bot

Oven-Bot is a modular Discord-first product-ad creative pipeline. A user submits one Discord message with product images and a spec sheet; the bot creates a job thread, stages the attachments, runs the creative pipeline, and keeps the thread open for approval and targeted revisions.

The repository currently includes the **Discord intake, job state, attachment staging, approval loop, and a runnable development pipeline**. Meshy, Blender, and Google Drive are deliberately behind a `Pipeline` interface so they can be added without changing Discord event handling.

## Workflow

```text
Discord message + attachments
  -> dedicated Discord thread
  -> download and stage inputs
  -> pipeline adapter (Meshy / Blender / Drive)
  -> post preview and wait for approval
  -> classify feedback
  -> targeted revision or approve
```

### What is agentic?

The transport and file operations are deterministic. The decision points belong in the pipeline adapter:

- choose the strongest source image for 3D generation;
- evaluate whether a generated model is usable;
- select product-appropriate camera and lighting;
- route feedback to re-edit, re-render, or 3D regeneration.

`feedback.py` contains a small deterministic router for the MVP. It is intentionally isolated so it can later be replaced by an LLM-backed decision adapter.

## Project layout

```text
src/oven_bot/
  attachments.py  # validation, safe names, and Discord URL downloads
  config.py       # environment-backed settings
  discord_bot.py  # Discord events and job/thread orchestration
  feedback.py     # feedback-to-pipeline routing
  models.py       # job state and domain models
  pipeline.py     # replaceable pipeline protocol and dev adapter
  store.py        # JSON job repository
tests/            # focused unit tests
```

## Setup

Requires Python 3.11 or newer.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Set `DISCORD_TOKEN` in `.env`. `DISCORD_INPUT_CHANNEL_ID` and `DISCORD_ALLOWED_GUILD_ID` are optional but recommended for limiting where jobs can start.

Invite the bot with these permissions:

- View Channels
- Send Messages
- Read Message History
- Create Public Threads
- Send Messages in Threads
- Attach Files
- Embed Links

Enable the **Message Content Intent** for the bot in the Discord Developer Portal. The code enables the corresponding gateway intent.

Run:

```powershell
$env:PYTHONPATH = "src"
python -m oven_bot
```

## Discord usage

Post one message in the configured input channel with at least one `.png`, `.jpg`, `.jpeg`, or `.webp` attachment. Optional spec formats are `.pdf`, `.txt`, `.csv`, and `.xlsx`.

The bot creates a thread and posts progress there. Once the pipeline finishes, reply in the thread with:

- `approve` / `approved` / `lgtm`
- `Make it brighter` or `change the angle` for a render revision
- `The CTA text is too small` for a layout revision
- `The model is wrong` or `use the other image` for 3D regeneration

Jobs are persisted to `data/jobs.json`; downloaded files and pipeline outputs live under `data/<job-id>/`. These paths are ignored by Git.

## Integrating Meshy, Blender, and Drive

Implement the `Pipeline` protocol in `pipeline.py` (or a separate module) and inject it in `build_bot`. Keep each external service as its own adapter:

```python
class ProductionPipeline:
    async def run(self, job, progress):
        # select image -> Meshy -> quality check -> Blender -> Drive
        ...

    async def revise(self, job, action, feedback, progress):
        # rerun only the affected stage
        ...
```

The Discord layer only knows about `run`, `revise`, progress messages, and job state. This keeps provider credentials and API-specific behavior out of the bot.

## Tests

```powershell
$env:PYTHONPATH = "src"
pytest
```

## Production hardening still needed

- Replace the JSON repository with SQLite/Postgres for concurrent workers.
- Add a queue/worker process for multiple simultaneous jobs.
- Add a real Meshy client, Blender MCP client, and Google Drive adapter.
- Persist external task IDs and retry only safe/idempotent operations.
- Add authentication/authorization checks for who can approve a job.
- Add structured logs and secrets management.
