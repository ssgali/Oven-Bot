import base64
import io
import json
import os
import re
import urllib.error
import urllib.request

from PIL import Image
from pydantic import ValidationError

defaultModels = {"hf": "Qwen/Qwen3.8-27B", "ollama": "qwen3-vl:2b"}
ollamaUrl = "http://localhost:11434"


class VlmError(Exception):
    pass


def encodeImage(image, maxSize=1024):
    if not isinstance(image, Image.Image):
        image = Image.open(image)
        image.load()
    image = image.convert("RGB")
    image.thumbnail((maxSize, maxSize), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def extractJson(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text


def inlineRefs(schema):
    """Some providers reject $ref in json_schema; pydantic emits $defs for nested models."""
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(dict(defs[node["$ref"].split("/")[-1]]))
            return {k: resolve(v) for k, v in node.items()}
        return [resolve(v) for v in node] if isinstance(node, list) else node

    return resolve(schema)


class VlmClient:
    """Vision-language model behind one call: askJson(prompt, pydanticModel, images) → validated model.
    hf: Hugging Face Inference Providers (token from HF_TOKEN or `hf auth login`).
    ollama: local server; its native /api/chat enforces the JSON schema with a grammar, which small models need."""

    def __init__(self, backend=None, model=None, timeout=180):
        self.backend = backend or os.environ.get("OVEN_VLM_BACKEND", "hf")
        if self.backend not in defaultModels:
            raise ValueError(f"backend must be one of {list(defaultModels)}")
        self.model = model or os.environ.get("OVEN_VLM_MODEL") or defaultModels[self.backend]
        self.timeout = timeout
        if self.backend == "hf":
            from huggingface_hub import InferenceClient
            self.client = InferenceClient(provider=os.environ.get("OVEN_VLM_PROVIDER", "auto"), timeout=timeout)
        else:
            self.url = os.environ.get("OVEN_OLLAMA_URL", ollamaUrl).rstrip("/")

    def __repr__(self):
        return f"VlmClient({self.backend}:{self.model})"

    def hfChat(self, messages, schema, maxTokens, temperature):
        from huggingface_hub.errors import HfHubHTTPError

        wire = [{"role": m["role"], "content": [
            *({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in m["images"]),
            {"type": "text", "text": m["content"]}]} if m.get("images") else m for m in messages]
        fmt = schema and {"type": "json_schema", "json_schema": {
            "name": schema.__name__, "schema": inlineRefs(schema.model_json_schema()), "strict": True}}
        try:
            r = self.client.chat_completion(wire, model=self.model, max_tokens=maxTokens, temperature=temperature,
                                            response_format=fmt)
        except HfHubHTTPError as e:
            status = getattr(e.response, "status_code", None)
            if fmt and status in (400, 422):  # provider without structured output: rely on prompt + validation
                return self.hfChat(messages, None, maxTokens, temperature)
            raise VlmError(f"{self!r} HTTP {status}: {str(e)[:300]}") from e
        except Exception as e:
            raise VlmError(f"{self!r} request failed: {type(e).__name__}: {str(e)[:300]}") from e
        return r.choices[0].message.content or ""

    def ollamaChat(self, messages, schema, maxTokens, temperature):
        body = {"model": self.model, "messages": messages, "stream": False,
                "options": {"temperature": temperature, "num_predict": maxTokens}}
        if schema:
            body["format"] = inlineRefs(schema.model_json_schema())
        req = urllib.request.Request(f"{self.url}/api/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            raise VlmError(f"{self!r} HTTP {e.code}: {e.read()[:300].decode(errors='replace')}") from e
        except OSError as e:
            raise VlmError(f"{self!r} unreachable at {self.url} ({e}); is `ollama serve` running "
                           f"and `ollama pull {self.model}` done?") from e
        return data.get("message", {}).get("content", "")

    def askJson(self, prompt, schema, images=(), system=None, maxTokens=2000, temperature=0.2):
        chat = self.ollamaChat if self.backend == "ollama" else self.hfChat
        user = {"role": "user", "content": prompt}
        if images:
            user["images"] = [encodeImage(i) for i in images]
        messages = ([{"role": "system", "content": system}] if system else []) + [user]
        text = chat(messages, schema, maxTokens, temperature)
        try:
            return schema.model_validate_json(extractJson(text))
        except ValidationError as e:
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"That reply did not match the JSON schema: {e.errors()[:3]}. "
                                                     "Reply with only the corrected JSON object."}]
        text = chat(messages, schema, maxTokens, temperature)
        try:
            return schema.model_validate_json(extractJson(text))
        except ValidationError as e:
            raise VlmError(f"{self!r} returned invalid JSON twice: {e.errors()[:2]}; got {text[:300]!r}") from e
