from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from ..vlm import encodeImage
from ..vlm.vlm import extractJson, inlineRefs


def imageContent(prompt, images):
    if not images:
        return prompt
    parts = [{"type": "text", "text": prompt}]
    parts += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encodeImage(i)}"}} for i in images]
    return parts


def isHuggingFace(model):
    from langchain_huggingface import ChatHuggingFace
    return isinstance(model, ChatHuggingFace)


def hfResponseFormat(schema):
    """The exact response_format shape agent/vlm/vlm.py's hfChat already proves works against HF
    Inference Providers. ChatHuggingFace.with_structured_output()'s own "function_calling" method raises
    NotImplementedError for a pydantic schema, and its "json_schema" method sends response_format as
    {"type": "json_object", "schema": ...}, which this provider rejects with wrong_api_format (confirmed
    live) — both bugs in langchain-huggingface 1.2.2, not in the provider. Binding this shape directly and
    parsing the raw text ourselves (like vlm.py does) sidesteps both."""
    return {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": inlineRefs(schema.model_json_schema()),
                                                    "strict": True}}


def askStructured(model, prompt, schema, images=(), system=None):
    """Structured output with one retry on validation failure — mirrors VlmClient.askJson's contract.
    Ollama's ChatOllama.with_structured_output() (default method="json_schema") is reliable and used as-is.
    ChatHuggingFace needs the manual bind+parse path in askStructuredHf (see hfResponseFormat)."""
    if isHuggingFace(model):
        return askStructuredHf(model, prompt, schema, images, system)
    structured = model.with_structured_output(schema, include_raw=True)
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [HumanMessage(content=imageContent(prompt, images))]
    r = structured.invoke(messages)
    if r["parsed"] is not None:
        return r["parsed"]
    error = r["parsing_error"]
    errors = error.errors()[:3] if isinstance(error, ValidationError) else [str(error)]
    messages += [r["raw"], {"role": "user",
                            "content": f"That reply did not match the JSON schema: {errors}. "
                                       "Reply with only the corrected JSON object."}]
    r = structured.invoke(messages)
    if r["parsed"] is not None:
        return r["parsed"]
    raise ValueError(f"{model} returned invalid structured output twice: {r['parsing_error']}")


def askStructuredHf(model, prompt, schema, images, system):
    bound = model.bind(response_format=hfResponseFormat(schema))
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [HumanMessage(content=imageContent(prompt, images))]
    ai = bound.invoke(messages)
    try:
        return schema.model_validate_json(extractJson(ai.content))
    except ValidationError as e:
        messages += [ai, {"role": "user",
                          "content": f"That reply did not match the JSON schema: {e.errors()[:3]}. "
                                     "Reply with only the corrected JSON object."}]
    ai = bound.invoke(messages)
    try:
        return schema.model_validate_json(extractJson(ai.content))
    except ValidationError as e:
        raise ValueError(f"{model} returned invalid structured output twice: {e.errors()[:2]}") from e
