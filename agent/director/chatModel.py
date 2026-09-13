import os

defaultModels = {"ollama": "qwen3-vl:8b", "hf": "Qwen/Qwen3.8-27B"}
ollamaUrl = "http://localhost:11434"


def makeChatModel(backend=None, model=None, temperature=0.2):
    """LangChain chat model for the director agent. Ollama is the default: its bind_tools()/
    with_structured_output() are reliable. HF Inference Providers' tool-calling assumes OpenAI-style
    tool_calls, which not every provider/model emits — best-effort only, matching vlm.py's posture."""
    backend = backend or os.environ.get("OVEN_DIRECTOR_BACKEND", "ollama")
    model = model or os.environ.get("OVEN_DIRECTOR_MODEL") or defaultModels[backend]
    if backend == "ollama":
        from langchain_ollama import ChatOllama
        url = os.environ.get("OVEN_OLLAMA_URL", ollamaUrl)
        return ChatOllama(model=model, base_url=url, temperature=temperature)
    if backend == "hf":
        from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint
        endpoint = HuggingFaceEndpoint(repo_id=model, provider=os.environ.get("OVEN_VLM_PROVIDER", "auto"),
                                       temperature=temperature)
        return ChatHuggingFace(llm=endpoint)
    raise ValueError(f"backend must be one of {list(defaultModels)}, got {backend!r}")
