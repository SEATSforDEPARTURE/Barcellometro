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


def model_display_name(model_str: str | None) -> str:
    raw = str(model_str or "").strip()
    if not raw:
        return ""
    provider, model = parse_model_string(raw)
    model = model.strip()
    if not model:
        return ""
    if provider == "ollama":
        return model.split(":", 1)[0].strip() or model
    return model
