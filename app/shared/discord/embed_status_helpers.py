from __future__ import annotations

from app.services.footer import footer_service_category

CAMPAIGN_EDITORIAL_SERVICES = {
    "campagne_notizie",
    "campagne_meteo",
    "campagne_oroscopo",
}
CAMPAIGN_PROMPT_SERVICE = "campagne_prompt"
CAMPAIGN_TIMER_SERVICE = "campagne_timer"


def _service_section(service_name: str) -> int:
    return footer_service_category(service_name)


def _split_long_text(text: str, max_len: int = 1900) -> list[str]:
    clean_text = text.strip()
    if not clean_text:
        return []
    if len(clean_text) <= max_len:
        return [clean_text]

    parts: list[str] = []
    for line in clean_text.split("\n"):
        if len(line) <= max_len:
            parts.append(line)
            continue
        for idx in range(0, len(line), max_len):
            parts.append(line[idx : idx + max_len])

    chunks: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}\n{part}" if current else part
        if len(candidate) <= max_len:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = part
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]


def _chunk_status_blocks(blocks: list[str], max_len: int = 1900) -> list[str]:
    chunks: list[str] = []
    current = ""

    for raw_block in blocks:
        block = raw_block.strip()
        if not block:
            continue
        if len(block) > max_len:
            split_blocks = _split_long_text(block, max_len=max_len)
        else:
            split_blocks = [block]

        for split_block in split_blocks:
            candidate = f"{current}\n\n{split_block}" if current else split_block
            if len(candidate) <= max_len:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = split_block
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk]
