from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from validate_embed_standards import validate_embed_standards


def test_embed_standards_validator_has_no_errors() -> None:
    report = validate_embed_standards()

    assert report.errors == []
