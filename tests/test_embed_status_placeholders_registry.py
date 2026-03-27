from __future__ import annotations

from app.services.embed_status_placeholders import (
    format_placeholder_status_lines,
    list_embed_status_placeholders,
    placeholder_names_for_system,
)


def test_placeholder_registry_has_unique_names_and_descriptions() -> None:
    registry = list_embed_status_placeholders()
    names = [item.name for item in registry]

    assert len(names) == len(set(names))
    assert all(item.description.strip() for item in registry)


def test_placeholder_registry_system_mapping_is_coherent() -> None:
    author_names = placeholder_names_for_system("author")
    footer_names = placeholder_names_for_system("footer")
    description_names = placeholder_names_for_system("description")

    assert {"service_name", "service_label", "bot_version"}.issubset(author_names)
    assert {"service_name", "service_label", "bot_version"}.issubset(footer_names)
    assert "user_name" not in author_names
    assert "audio_intro" not in footer_names

    assert {"user_name", "service_name", "ordinal_today"}.issubset(description_names)
    assert "service_label" not in description_names


def test_status_lines_are_never_empty_for_supported_systems() -> None:
    for system in ("author", "footer", "description"):
        lines = format_placeholder_status_lines(system)
        assert lines
        assert all(name.startswith("{") and name.endswith("}") for name, _ in lines)
        assert all(description.strip() for _, description in lines)
