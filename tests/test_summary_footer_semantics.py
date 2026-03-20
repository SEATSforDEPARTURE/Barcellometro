from pathlib import Path


def test_riassunto_footer_logic_uses_used_ai_output_fields() -> None:
    source = Path("app/plugins/commands_modular/riassunto.py").read_text()
    assert 'used_ai_output = bool(ai_status.get("used_ai_output"))' in source
    assert 'used_display_model = str(ai_status.get("used_display_model") or "").strip()' in source
    assert 'contributors = [used_display_model] if used_ai_output and used_display_model else []' in source
    assert 'return contributors, (not used_ai_output)' in source


def test_channel_summary_footer_logic_uses_used_ai_output_fields() -> None:
    source = Path("app/services/channel_summary_service.py").read_text()
    assert 'used_ai_output = bool(ai_status.get("used_ai_output"))' in source
    assert 'used_display_model = str(ai_status.get("used_display_model") or "").strip()' in source
    assert 'contributors = [used_display_model] if used_ai_output and used_display_model else []' in source
    assert 'return contributors, (not used_ai_output)' in source
    assert '(ai_reason == "ok" or ai_called)' not in source


def test_footer_renderer_forbids_local_only_wording() -> None:
    source = Path("app/services/footer.py").read_text()
    assert "Dati elaborati" + " in loco" not in source


def test_riassunto_row_access_uses_row_safe_helper_for_records() -> None:
    source = Path("app/plugins/commands_modular/riassunto.py").read_text()
    assert 'def _row_get(row: Any, key: str, default: Any = None) -> Any:' in source
    assert 'record.get("content")' not in source
    assert 'record.get("author_id")' not in source
    assert 'record.get("origin")' not in source


def test_embed_docs_document_new_footer_and_section_rules() -> None:
    source = Path("docs/embed_command_rendering_standard.md").read_text()
    assert "Il body non deve mai riusare la stessa icona del sottotitolo nelle sezioni" in source
    assert "locale-only è abolita" in source
