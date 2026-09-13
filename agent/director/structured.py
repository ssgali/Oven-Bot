from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from ..vlm import encodeImage


def imageContent(prompt, images):
    if not images:
        return prompt
    parts = [{"type": "text", "text": prompt}]
    parts += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encodeImage(i)}"}} for i in images]
    return parts


def askStructured(model, prompt, schema, images=(), system=None):
    """with_structured_output(), retried once on validation failure — mirrors VlmClient.askJson's contract
    (LangChain's structured-output helper does not retry on its own)."""
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
