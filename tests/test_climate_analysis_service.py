import asyncio
import json
from unittest.mock import AsyncMock, Mock

from app.services.climate_analysis_service import ClimateAnalysisService


def test_rule_based_venting_with_profanity_not_direct_conflict() -> None:
    service = ClimateAnalysisService()
    out = service.classify_rule_based(content="oggi sto incazzato, che giornata di merda", mentions=[], reply_to_id="").to_dict()
    assert out["label"] == "venting"
    assert out["target_type"] == "none"


def test_rule_based_heated_non_conflict() -> None:
    service = ClimateAnalysisService()
    out = service.classify_rule_based(content="NOOO TI PREGOOO!!!", mentions=[], reply_to_id="").to_dict()
    assert out["label"] == "heated_non_conflict"


def test_rule_based_directed_conflict_and_deescalation() -> None:
    service = ClimateAnalysisService()
    conflict = service.classify_rule_based(content="sei ridicolo <@2>", mentions=["2"], reply_to_id="").to_dict()
    calm = service.classify_rule_based(content="calma, chiudiamola qui", mentions=[], reply_to_id="").to_dict()
    assert conflict["label"] == "directed_conflict"
    assert calm["label"] == "deescalation"


def test_validate_payload_rejects_invalid_enum_or_range() -> None:
    service = ClimateAnalysisService()
    bad = {
        "label": "unknown",
        "toxicity": 1.2,
        "aggression": 0.0,
        "directedness": 0.0,
        "profanity": 0.0,
        "venting": 0.0,
        "calming": 0.0,
        "conflict": 0.0,
        "target_type": "none",
        "confidence": 0.3,
        "reason_code": "x",
    }
    assert service.validate_payload(bad) is None


def test_ai_invalid_output_falls_back_to_rule_only() -> None:
    ai = Mock()
    ai.is_enabled = Mock(return_value=True)
    ai.ask_for_task_with_validator = AsyncMock(return_value=None)
    ai.get_runtime_model_contributors = Mock(return_value=[])
    service = ClimateAnalysisService(ai)
    metrics, contributors = asyncio.run(
        service.analyze_window(
            rows=[{"author_id": "u1", "content": "ma che cazzo dici?? <@2>", "mentions_json": json.dumps(["2"])}],
            max_ai_messages=1,
        )
    )
    assert metrics["direct_conflict_index"] == 1.0
    assert metrics["ai_used"] is False
    assert contributors == []
