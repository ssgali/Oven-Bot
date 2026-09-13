import json
from pathlib import Path
from typing import Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from blender.video import animateShots, encodeFrames, renderRange
from compose.videoOverlay import compositeOverlays

from .chatModel import makeChatModel
from .paths import JobPaths
from .prompts import directorSystem, reviseSystem, revisePrompt, scriptPrompt
from .schema import VideoScript, diffScript, resolveScope
from .structured import askStructured, imageContent
from .tools import makeDirectorTools

maxReviseSteps = 8


class DirectorState(TypedDict):
    jobId: str
    images: list[str]
    specBlurb: str
    objName: str
    fps: int
    aspect: str
    longEdge: int
    engine: str
    samples: int | None
    versionDir: str
    script: dict
    scriptHistory: list[dict]
    videoPath: str | None
    critique: str | None
    critiqueHistory: list[dict]


def jobPathsFor(state):
    return JobPaths(Path(state["versionDir"]), state["engine"], state.get("samples"))


def generateScriptNode(state, config):
    say = config["configurable"]["progress"]
    model = makeChatModel(config["configurable"].get("scriptBackend"))
    prompt = scriptPrompt(state["specBlurb"], state["fps"], state["aspect"])
    script = askStructured(model, prompt, VideoScript, state["images"], directorSystem)
    script = script.model_copy(update={"objName": state["objName"]})
    say(f"Script drafted: {len(script.shots)} shot(s), {script.totalFrames} frames at {script.fps}fps.")
    scriptDict = script.model_dump()
    return {"script": scriptDict, "scriptHistory": [scriptDict]}


def renderNode(state, config):
    client = config["configurable"]["client"]
    say = config["configurable"]["progress"]
    jobPaths = jobPathsFor(state)
    script = state["script"]
    say("Building the studio and keyframing the timeline…")
    animateShots(client, script)
    say(f"Rendering {script['totalFrames'] + 1} frame(s)…")
    renderRange(client, jobPaths.rawDir, 0, script["totalFrames"], jobPaths.engine, jobPaths.samples)
    compositeOverlays(jobPaths.rawDir, script, jobPaths.compositedDir)
    r = encodeFrames(jobPaths.compositedDir, jobPaths.videoPath, script["fps"])
    say(f"Encoded {r['outPath']}.")
    return {"videoPath": r["outPath"]}


def presentForReviewNode(state):
    """Pauses the graph until VideoPipeline.revise() resumes it with the reviewer's free-text critique.
    Approval never reaches here: discordBot.py resolves FeedbackAction.APPROVE on its own and simply stops
    calling revise() — the checkpoint then just sits idle, same as an approved hero job stops re-rendering."""
    critique = interrupt({"videoPath": state["videoPath"], "shotIds": [s["id"] for s in state["script"]["shots"]]})
    return {"critique": critique}


def reviseScriptNode(state, config):
    """Hand-rolled tool-calling loop (not create_react_agent, so propose_revision/finish_revision can force
    a structured decision): the model must commit to a revision plan before touching any render tool, and
    code (not the model) has the final say on how much of the timeline actually needs re-rendering."""
    client = config["configurable"]["client"]
    say = config["configurable"]["progress"]
    jobPaths = jobPathsFor(state)
    oldScript = VideoScript.model_validate(state["script"])
    scriptBox = {"script": state["script"]}
    decision = {}

    @tool
    def propose_revision(affectedShotIds: list[str], scope: Literal["scoped", "global"], newScript: dict,
                         reason: str) -> str:
        """Commit to a specific script revision before using any rendering tool. `newScript` must be the
        complete updated script (every shot, not just the changed ones)."""
        try:
            newScriptObj = VideoScript.model_validate(newScript)
        except ValidationError as e:
            return f"newScript is invalid: {e.errors()[:3]}. Fix it and call propose_revision again."
        actual = diffScript(oldScript, newScriptObj)
        effective = set(affectedShotIds) | actual
        resolvedScope, frameRange = resolveScope(newScriptObj, effective, scope)
        scriptBox["script"] = newScriptObj.model_dump()
        decision.update(scope=resolvedScope, frameRange=list(frameRange), shotIds=sorted(effective), reason=reason)
        say(f"Revision proposed ({resolvedScope}, frames {frameRange[0]}-{frameRange[1]}): {reason}")
        lo, hi = frameRange
        nextStep = "render_full()" if resolvedScope == "global" else f"render_range({lo}, {hi})"
        return (f"Committed. Affected frames [{lo}, {hi}]. If ONLY textOverlays changed on these shots, call "
                f"recomposite_overlays({lo}, {hi}) then encode_video; otherwise call {nextStep}.")

    @tool
    def finish_revision(summary: str) -> str:
        """Call once the rendered result satisfies the critique and no further tool calls are needed."""
        return "done"

    tools = makeDirectorTools(client, jobPaths, scriptBox) + [propose_revision, finish_revision]
    toolsByName = {t.name: t for t in tools}
    model = makeChatModel(config["configurable"].get("reviseBackend")).bind_tools(tools)

    messages = [SystemMessage(reviseSystem),
               HumanMessage(content=imageContent(
                   revisePrompt(state["script"], state["critique"], state["critiqueHistory"]), []))]
    finished = False
    for _ in range(maxReviseSteps):
        ai = model.invoke(messages)
        messages.append(ai)
        if not ai.tool_calls:
            break
        for call in ai.tool_calls:
            toolFn = toolsByName.get(call["name"])
            try:
                result = toolFn.invoke(call["args"]) if toolFn else f"unknown tool {call['name']!r}"
            except Exception as e:
                result = f"{type(e).__name__}: {e}"
            if call["name"] == "extract_preview_frame" and isinstance(result, str) and Path(result).is_file():
                messages.append(ToolMessage(content="preview frame attached below", tool_call_id=call["id"]))
                messages.append(HumanMessage(content=imageContent("Requested preview frame:", [result])))
            else:
                messages.append(ToolMessage(content=json.dumps(result, default=str), tool_call_id=call["id"]))
            if call["name"] == "finish_revision":
                finished = True
        if finished:
            break
    else:
        say("Revision loop hit its step limit without an explicit finish; using the last committed result.")

    critiqueHistory = state["critiqueHistory"] + [{"feedback": state["critique"], **decision}]
    return {"script": scriptBox["script"], "scriptHistory": state["scriptHistory"] + [scriptBox["script"]],
            "videoPath": str(jobPaths.videoPath), "critiqueHistory": critiqueHistory}


def buildDirectorGraph(checkpointer):
    graph = StateGraph(DirectorState)
    graph.add_node("generate_script", generateScriptNode)
    graph.add_node("render", renderNode)
    graph.add_node("present_for_review", presentForReviewNode)
    graph.add_node("revise_script", reviseScriptNode)
    graph.add_edge(START, "generate_script")
    graph.add_edge("generate_script", "render")
    graph.add_edge("render", "present_for_review")
    graph.add_edge("present_for_review", "revise_script")
    graph.add_edge("revise_script", "present_for_review")
    return graph.compile(checkpointer=checkpointer)
