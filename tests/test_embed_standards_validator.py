from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from validate_embed_standards import validate_embed_standards


def test_embed_standards_validator_has_no_errors() -> None:
    report = validate_embed_standards()

    assert report.errors == []


FORBIDDEN_FOOTER_PHRASES = (
    "Dati elaborati" + " in loco",
    "e fallback" + " locale",
)


def test_project_has_no_legacy_footer_phrases_in_scanned_dirs() -> None:
    scan_roots = (Path("settings"), Path("app"), Path("tests"), Path("docs"))
    text_suffixes = {".py", ".json", ".md", ".txt"}

    for root in scan_roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in text_suffixes:
                continue
            source = path.read_text(encoding="utf-8")
            for forbidden in FORBIDDEN_FOOTER_PHRASES:
                assert forbidden not in source, f"Forbidden footer phrase found in {path}: {forbidden}"


def test_footer_service_has_no_implicit_default_phrase_fallback() -> None:
    source = Path("app/services/footer.py").read_text(encoding="utf-8")

    assert "FOOTER_DEFAULT_PHRASE" not in source
    assert "global_phrase or None" in source


def test_command_embed_helpers_do_not_default_to_minimal_or_attach_local_footer_text() -> None:
    source = Path("app/shared/discord/command_embeds.py").read_text(encoding="utf-8")

    assert 'footer_mode: FooterMode = "minimal"' not in source
    assert "attach_minimal_footer(" not in source
