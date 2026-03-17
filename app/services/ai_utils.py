def parse_model_string(model_str: str) -> tuple[str, str]:
    """
    Esempi:
    openai:gpt-4o-mini
    ollama:qwen2.5:1.5b
    """
    if ":" not in model_str:
        return "openai", model_str

    provider, model = model_str.split(":", 1)
    return provider, model
