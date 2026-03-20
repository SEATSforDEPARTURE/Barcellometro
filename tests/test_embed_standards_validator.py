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
