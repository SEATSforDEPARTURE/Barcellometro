from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


LABELS = {"neutral", "positive", "venting", "heated_non_conflict", "directed_conflict", "deescalation"}
TARGET_TYPES = {"none", "generic", "user", "group"}
PROFANITY = {"cazzo", "merda", "stronzo", "vaffanculo", "fanculo", "minchia", "porca", "troia", "puttana", "coglione", "bastardo"}
INSULTS = {"ridicolo", "idiota", "stupido", "scemo", "patetico", "fallito", "imbecille", "deficiente", "pagliaccio", "inetto"}
BLASPHEMY_PATTERNS = [r"\bporco\s+dio\b", r"\bdio\s+cane\b", r"\bdio\s+boia\b", r"\bmadonna\s+puttana\b", r"\bporca\s+madonna\b"]
CHALLENGE_PATTERNS = [r"\bma che .* dici\b", r"\bchi ti credi\b", r"\bnon capisci niente\b", r"\bhai rotto\b"]
CALMING = {"calma", "calmi", "tranquilli", "non litigate", "chiudiamola qui", "parliamone con calma"}
VENTING_PATTERNS = [r"\bio\b.*\b(sto|sono)\b.*\b(incazzat|nervos|esaust|stanch|arrabbiat)", r"\bche giornat[ae]\b", r"\bmi sono rotto\b"]
SECOND_PERSON = [r"\btu\b", r"\bsei\b", r"\bstai\b", r"\bdici\b", r"\bvoi\b"]


@dataclass(frozen=True)
class ClimateClassification:
    label: str
    toxicity: float
    aggression: float
    directedness: float
    profanity: float
    venting: float
    calming: float
    conflict: float
    target_type: str
    confidence: float
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "toxicity": round(self.toxicity, 3),
            "aggression": round(self.aggression, 3),
            "directedness": round(self.directedness, 3),
            "profanity": round(self.profanity, 3),
            "venting": round(self.venting, 3),
            "calming": round(self.calming, 3),
            "conflict": round(self.conflict, 3),
            "target_type": self.target_type,
            "confidence": round(self.confidence, 3),
            "reason_code": self.reason_code,
        }


class ClimateAnalysisService:
    def __init__(self, ai_service: Any | None = None) -> None:
        self._ai = ai_service

    @staticmethod
    def validate_payload(payload: Any) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        required = {"label", "toxicity", "aggression", "directedness", "profanity", "venting", "calming", "conflict", "target_type", "confidence", "reason_code"}
        if set(payload.keys()) != required:
            return None
        if payload["label"] not in LABELS or payload["target_type"] not in TARGET_TYPES:
            return None
        if not isinstance(payload["reason_code"], str) or not payload["reason_code"].strip():
            return None
        for key in {"toxicity", "aggression", "directedness", "profanity", "venting", "calming", "conflict", "confidence"}:
            value = payload.get(key)
            try:
                val = float(value)
            except (TypeError, ValueError):
                return None
            if val < 0.0 or val > 1.0:
                return None
            payload[key] = val
        return payload

    def classify_rule_based(self, *, content: str, mentions: list[str], reply_to_id: str) -> ClimateClassification:
        text = self._normalize_text(content)
        profanity_hits = sum(1 for word in PROFANITY if word in text)
        insult_hits = sum(1 for word in INSULTS if word in text)
        blasphemy_hits = sum(1 for pattern in BLASPHEMY_PATTERNS if re.search(pattern, text))
        challenge_hits = sum(1 for pattern in CHALLENGE_PATTERNS if re.search(pattern, text))
        calming_hits = sum(1 for word in CALMING if word in text)
        venting_hits = sum(1 for pattern in VENTING_PATTERNS if re.search(pattern, text))
        second_person_hits = sum(1 for pattern in SECOND_PERSON if re.search(pattern, text))
        caps_ratio = self._caps_ratio(content)
        repeated_punctuation = content.count("!!") + content.count("??")

        has_target = bool(mentions or reply_to_id or second_person_hits > 0)
        target_type = "user" if (mentions or reply_to_id) else ("group" if "voi" in text or "ragazzi" in text or "raga" in text else ("generic" if second_person_hits else "none"))
        toxicity = min(1.0, (0.14 * profanity_hits) + (0.28 * insult_hits) + (0.5 * blasphemy_hits))
        aggression = min(1.0, toxicity + (0.22 if repeated_punctuation else 0.0) + (0.2 if caps_ratio > 0.35 else 0.0) + (0.14 * challenge_hits))
        directedness = min(1.0, (0.6 if has_target else 0.0) + (0.16 if second_person_hits else 0.0) + (0.1 if challenge_hits else 0.0))
        venting = min(1.0, (0.5 * venting_hits) + (0.15 if "io" in text and not has_target else 0.0))
        calming = min(1.0, 0.5 * calming_hits)
        conflict = min(1.0, (aggression * 0.45) + (directedness * 0.35) + (toxicity * 0.2))

        label = "neutral"
        reason = "neutral_no_target"
        if calming >= 0.35:
            label, reason = "deescalation", "calming_language"
        elif directedness >= 0.6 and (insult_hits > 0 or aggression >= 0.42 or blasphemy_hits > 0):
            label, reason = "directed_conflict", "attack_with_target"
        elif venting >= 0.4 and directedness < 0.4:
            label, reason = "venting", "self_venting"
        elif aggression >= 0.35 and directedness < 0.5:
            label, reason = "heated_non_conflict", "high_intensity_no_target"
        elif any(token in text for token in ["grazie", "brav", "ottimo"]):
            label, reason = "positive", "positive_affect"

        return ClimateClassification(
            label=label,
            toxicity=toxicity,
            aggression=aggression,
            directedness=directedness,
            profanity=min(1.0, profanity_hits * 0.3),
            venting=venting,
            calming=calming,
            conflict=conflict,
            target_type=target_type,
            confidence=0.76,
            reason_code=reason,
        )

    @staticmethod
    def _normalize_text(content: str) -> str:
        lowered = (content or "").lower()
        normalized = unicodedata.normalize("NFKD", lowered)
        stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", stripped).strip()

    async def classify_with_ai(self, *, content: str, author_id: str, mentions: list[str], reply_to_id: str, micro_context: list[dict[str, str]]) -> dict[str, Any] | None:
        if self._ai is None or not self._ai.is_enabled():
            return None
        prompt = json.dumps(
            {
                "message": {"author_id": author_id, "content": content, "reply_to_author_id": reply_to_id, "mentioned_user_ids": mentions},
                "micro_context": micro_context[-5:],
                "rules": [
                    "parolacce da sole non implicano directed_conflict",
                    "meglio venting/heated_non_conflict che falso directed_conflict",
                    "directed_conflict solo con target concreto",
                    "riconosci esplicitamente deescalation",
                ],
                "output": "Restituisci SOLO JSON conforme allo schema richiesto.",
            },
            ensure_ascii=False,
        )
        system = (
            "Sei un classificatore climate_analysis per chat Discord italiane colloquiali. "
            "Output STRICT JSON con i campi: label,toxicity,aggression,directedness,profanity,venting,calming,conflict,target_type,confidence,reason_code. "
            "Nessun testo extra."
        )

        def _validator(text: str) -> bool:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return False
            return self.validate_payload(parsed) is not None

        text = None
        if hasattr(self._ai, "ask_for_task_with_validator"):
            try:
                text = await self._ai.ask_for_task_with_validator("climate_analysis", prompt, system, validator=_validator)
            except TypeError:
                text = None
        if text is None:
            ask_for_task = getattr(self._ai, "ask_for_task", None)
            if ask_for_task is None:
                return None
            try:
                text = await ask_for_task("climate_analysis", prompt, system)
            except TypeError:
                return None
            if text and not _validator(text):
                text = None
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return self.validate_payload(parsed)

    async def analyze_window(self, *, rows: list[dict[str, Any]], max_ai_messages: int = 4) -> tuple[dict[str, Any], list[str]]:
        classifications: list[dict[str, Any]] = []
        ai_budget = max(0, max_ai_messages)
        ai_used = False
        for idx, row in enumerate(rows):
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            mentions = self._parse_mentions(row, content)
            reply_to = str(row.get("reply_to_author_id") or "")
            author_id = str(row.get("author_id") or "unknown")
            base = self.classify_rule_based(content=content, mentions=mentions, reply_to_id=reply_to).to_dict()
            ambiguous = (0.3 <= float(base["conflict"]) <= 0.6 and base["label"] in {"neutral", "heated_non_conflict", "venting"}) or idx == 0
            if ambiguous and ai_budget > 0:
                micro = [{"author_id": str(item.get("author_id") or ""), "content": str(item.get("content") or "")}
                         for item in rows[max(0, idx - 3):idx]]
                ai_result = await self.classify_with_ai(content=content, author_id=author_id, mentions=mentions, reply_to_id=reply_to, micro_context=micro)
                if ai_result is not None:
                    base = ai_result
                    ai_used = True
                ai_budget -= 1
            classifications.append(base)

        count = len(classifications)
        if count == 0:
            return {}, []
        direct_count = sum(1 for item in classifications if item["label"] == "directed_conflict")
        vent_count = sum(1 for item in classifications if item["label"] == "venting")
        deescal_count = sum(1 for item in classifications if item["label"] == "deescalation")
        reply_conflict_density = round(direct_count / max(count, 1), 3)
        metrics = {
            "hostility_index": round(sum(float(item["conflict"]) for item in classifications) / count, 3),
            "venting_index": round(vent_count / count, 3),
            "direct_conflict_index": round(direct_count / count, 3),
            "calming_index": round(sum(float(item["calming"]) for item in classifications) / count, 3),
            "profanity_index": round(sum(float(item["profanity"]) for item in classifications) / count, 3),
            "active_participation_index": round(sum(1 for item in classifications if item["label"] in {"positive", "neutral", "heated_non_conflict"}) / count, 3),
            "reply_conflict_density": reply_conflict_density,
            "message_classifications": classifications,
            "last_reason_code": str(classifications[-1].get("reason_code") or ""),
            "ai_used": ai_used,
        }
        models = self._ai.get_runtime_model_contributors("climate_analysis") if ai_used and self._ai is not None else []
        return metrics, models

    @staticmethod
    def _caps_ratio(content: str) -> float:
        total = sum(1 for ch in content if ch.isalpha())
        if total == 0:
            return 0.0
        upper = sum(1 for ch in content if ch.isalpha() and ch.isupper())
        return upper / total

    @staticmethod
    def _parse_mentions(row: dict[str, Any], content: str) -> list[str]:
        raw = row.get("mentions_json")
        if raw:
            try:
                parsed = json.loads(str(raw))
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                return []
        return re.findall(r"<@!?(\d+)>", content)
