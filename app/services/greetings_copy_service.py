from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.config.file_loader import load_json_file
from app.core.config_paths import GREETINGS_TRIGGER_EXAMPLE_JSON, GREETINGS_TRIGGER_JSON

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")

SUPPORTED_GREETINGS_EVENT_TYPES = {
    "join",
    "leave",
    "kick",
    "ban",
    "tempban",
    "grace",
    "inactive_kick",
    "inactive_tempban",
    "inactive_grace",
}

_ORDINALS_UPPER_MASCULINE = {
    1: "PRIMO",
    2: "SECONDO",
    3: "TERZO",
    4: "QUARTO",
    5: "QUINTO",
    6: "SESTO",
    7: "SETTIMO",
    8: "OTTAVO",
    9: "NONO",
    10: "DECIMO",
}

_ORDINALS_UPPER_FEMININE = {
    1: "PRIMA",
    2: "SECONDA",
    3: "TERZA",
    4: "QUARTA",
    5: "QUINTA",
    6: "SESTA",
    7: "SETTIMA",
    8: "OTTAVA",
    9: "NONA",
    10: "DECIMA",
}

_EVENT_LABELS = {
    "join": ("🤝", "ENTRATA", "f"),
    "leave": ("👋", "USCITA", "f"),
    "kick": ("👢", "ESPULSIONE", "f"),
    "ban": ("⛔", "INTERDIZIONE PERENNE", "f"),
    "tempban": ("⌛", "INTERDIZIONE TEMPORANEA", "f"),
    "grace": ("🕊️", "GRAZIA", "f"),
    "inactive_kick": ("👢", "ESPULSIONE", "f"),
    "inactive_tempban": ("⌛", "INTERDIZIONE TEMPORANEA", "f"),
    "inactive_grace": ("🕊️", "GRAZIA", "f"),
}

_BARCELLO_ALERTS = {
    "verde": "🟢 ALLERTA VERDE",
    "giallo": "🟡 ALLERTA GIALLA",
    "rosso": "🔴 ALLERTA ROSSA",
    "nero": "⚫ ALLERTA NERA",
}

_TEMPLATE_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")
_HIGHLIGHTED_PLACEHOLDERS = frozenset(
    {
        "mention",
        "display_name",
        "username",
        "user",
        "guild_name",
        "server",
        "moderator",
        "moderator_mention",
        "reason",
        "reason_suffix",
        "duration",
        "duration_days",
        "expires_at",
        "rejoin_link",
        "days_inactive",
        "inactivity_text",
        "event_label",
        "event_label_text",
        "occurrence_number",
        "occurrence_ordinal",
        "mood",
        "time_bucket",
        "count_tier",
        "barcello_state",
        "barcello_color",
        "barcello_alert",
        "barcello_score",
        "barcello_score_text",
    }
)

_REASON_BLOCK_EVENT_TYPES = frozenset(
    {
        "kick",
        "ban",
        "tempban",
        "grace",
        "inactive_kick",
        "inactive_grace",
    }
)

_MODERATION_REASON_BLOCK_HEADER = "**👇 La moderazione aggiunge:**"

_DEFAULT_GREETINGS_TRIGGER: dict[str, Any] = {
    "docs": {
        "placeholders": {
            "mention": {"description": "Mention Discord completa dell'utente."},
            "display_name": {"description": "Display name/nickname preferito dell'utente."},
            "username": {"description": "Username raw dell'utente."},
            "guild_name": {"description": "Nome del server."},
        }
    },
    "defaults": {
        "fallbacks": {
            "join": {
                "first_occurrence": ["{mention} arriva in {guild_name}. Benvenuto."],
                "repeat": ["{mention} torna in {guild_name}."],
                "default": ["{mention} passa da {guild_name}."],
            },
            "leave": {
                "first_occurrence": ["{mention} lascia {guild_name}."],
                "repeat": ["{mention} esce di nuovo da {guild_name}."],
                "default": ["{mention} saluta {guild_name}."],
            },
            "kick": {"default": ["{mention} viene allontanato da {guild_name}{reason_suffix}."]},
            "ban": {"default": ["{mention} riceve un ban da {guild_name}{reason_suffix}."]},
            "tempban": {"default": ["{mention} riceve un ban temporaneo da {guild_name} per {duration}{reason_suffix}."]},
            "grace": {"default": ["{mention} entra in periodo di grazia su {guild_name} per {duration}."]},
            "inactive_kick": {"default": ["{mention} viene allontanato da {guild_name} per inattività ({inactivity_text})."]},
            "inactive_tempban": {"default": ["{mention} riceve un ban temporaneo per inattività su {guild_name} per {duration} ({inactivity_text})."]},
            "inactive_grace": {"default": ["{mention} entra in grazia per inattività su {guild_name} per {duration} ({inactivity_text})."]},
        }
    },
    "mood_default": "accogliente",
    "time_buckets": {
        "night": {"start": 0, "end": 6},
        "morning": {"start": 6, "end": 12},
        "afternoon": {"start": 12, "end": 18},
        "evening": {"start": 18, "end": 24},
    },
    "count_tiers": [
        {"min_occurrence": 1, "label": "t1"},
        {"min_occurrence": 2, "label": "t2"},
        {"min_occurrence": 3, "label": "t3"},
    ],
    "templates": {
        "join": {
            "first_occurrence": ["{mention} entra in {server}."],
            "repeat": ["{mention} torna in {server}."],
            "default": ["{mention} passa da {server}."],
        },
        "leave": [
            "{mention} ha lasciato {server}.",
            "{mention} si allontana da {server}.",
        ],
        "kick": ["{mention} è stato allontanato da {server}{reason_suffix}."],
        "ban": ["{mention} è stato bannato da {server}{reason_suffix}."],
        "tempban": ["{mention} è stato escluso temporaneamente da {server} per {duration}{reason_suffix}."],
        "grace": ["{mention} riceve un periodo di grazia nel server {server} per {duration}."],
        "inactive_kick": ["{mention} viene allontanato da {server} per inattività ({inactivity_text})."],
        "inactive_tempban": ["{mention} riceve un ban temporaneo per inattività in {server} per {duration} ({inactivity_text})."],
        "inactive_grace": ["{mention} entra in periodo di grazia per inattività su {server} per {duration} ({inactivity_text})."],
    },
    "moods": {
        "accogliente": {
            "time": {
                "morning": {
                    "templates": {
                        "join": ["Buongiorno {mention}, benvenuto su {server}."],
                    }
                }
            },
            "barcello": {
                "verde": {
                    "templates": {
                        "join": ["{mention}, benvenuto su {server}. {barcello_alert}, cuore del server su **{barcello_score_text}**."],
                    }
                }
            },
            "count": {
                "t1": {
                    "templates": {
                        "join": ["{mention}, benvenuto su {server}."],
                    }
                },
                "t2": {
                    "templates": {
                        "join": ["{mention} torna su {server}."],
                    }
                },
                "t3": {
                    "templates": {
                        "join": ["{mention} rientra di nuovo su {server}."],
                    }
                },
            },
        },
        "teso": {
            "barcello": {
                "rosso": {
                    "templates": {
                        "kick": ["Clima già delicato: {mention} viene allontanato da {server}{reason_suffix}. {barcello_alert}."],
                        "ban": ["Con barcello rosso, {mention} riceve un ban da {server}{reason_suffix}. {barcello_alert}."],
                    }
                },
                "nero": {
                    "templates": {
                        "inactive_tempban": [
                            "Nel pieno dell'allerta nera, {mention} riceve un ban temporaneo per inattività in {server}. {barcello_alert}."
                        ],
                    }
                },
            },
            "count": {
                "t2": {
                    "templates": {
                        "join": ["{mention} torna in {server}, ma il clima resta teso."],
                        "leave": ["È già la seconda uscita: {mention} si allontana di nuovo da {server}."],
                    }
                },
                "t1": {
                    "templates": {
                        "join": ["{mention}, benvenuto in {server}. Il clima resta da osservare."],
                    }
                }
            },
        },
    },
}


@dataclass(frozen=True)
class GreetingsRenderResult:
    event_label: str
    occurrence_number: int
    template_context: dict[str, Any]
    narrative: str
    moderation_note: str | None
    mood: str
    time_bucket: str
    count_tier: str
    barcello_state: str
    raw_template: str


class GreetingsCopyService:
    def __init__(self, database: Any, *, barcello_service: Any | None = None, config_path: str | Path | None = None) -> None:
        self._database = database
        self._barcello_service = barcello_service
        self._config_path = config_path or GREETINGS_TRIGGER_JSON

    def build_template_context(
        self,
        *,
        user: Any,
        guild: Any,
        event_type_key: str,
        moderator: Any | None = None,
        reason: str | None = None,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
        rejoin_link: str | None = None,
        days_inactive: int | None = None,
        inactivity_text: str | None = None,
        occurrence_number: int = 1,
        mood: str | None = None,
        time_bucket: str | None = None,
        count_tier: str | None = None,
        barcello_color: str | None = None,
        barcello_score: int | None = None,
    ) -> dict[str, Any]:
        self._validate_event_type(event_type_key)
        username = getattr(user, "name", "Utente")
        display_name = getattr(user, "display_name", username)
        mention = getattr(user, "mention", f"<@{getattr(user, 'id', '0')}>")
        moderator_name = getattr(moderator, "display_name", getattr(moderator, "name", "Sistema")) if moderator else "Sistema"
        moderator_mention = getattr(moderator, "mention", moderator_name) if moderator else "Sistema"
        duration_human = self.format_duration_human(duration_seconds)
        duration_days = None if duration_seconds is None else max(1, int(duration_seconds // 86400))
        expires_text = expires_at.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC") if expires_at is not None else ""
        normalized_barcello = self.normalize_barcello_state(barcello_color)
        alert_line = self.format_barcello_alert_line(normalized_barcello)
        score_text = "n/d" if barcello_score is None else f"{int(barcello_score)}/100"
        event_label = format_greetings_event_label(event_type_key, occurrence_number)
        label_text = self._event_label_text(event_type_key)
        ordinal = self._format_ordinal_upper(event_type_key, occurrence_number)
        reason_text = reason or ""
        reason_suffix = f": {reason_text}" if reason_text else ""
        return {
            "user": username,
            "username": username,
            "display_name": display_name,
            "mention": mention,
            "tag": mention,
            "user_mention": mention,
            "user_id": str(getattr(user, "id", "")),
            "server": getattr(guild, "name", "Server"),
            "guild_name": getattr(guild, "name", "Server"),
            "guild_id": str(getattr(guild, "id", "")),
            "moderator": moderator_name,
            "moderator_mention": moderator_mention,
            "reason": reason_text,
            "reason_suffix": reason_suffix,
            "duration": duration_human or "",
            "duration_days": "" if duration_days is None else str(duration_days),
            "expires_at": expires_text,
            "rejoin_link": rejoin_link or "",
            "days_inactive": "" if days_inactive is None else str(days_inactive),
            "inactivity_text": inactivity_text or "",
            "event_type_key": event_type_key,
            "event_label": event_label,
            "event_label_text": label_text,
            "occurrence_number": str(max(1, int(occurrence_number))),
            "occurrence_ordinal": ordinal,
            "is_first_occurrence": max(1, int(occurrence_number)) == 1,
            "is_returning": event_type_key == "join" and max(1, int(occurrence_number)) >= 2,
            "mood": mood or "",
            "time_bucket": time_bucket or "",
            "count_tier": count_tier or "",
            "barcello_color": normalized_barcello,
            "barcello_state": normalized_barcello,
            "barcello_alert": alert_line,
            "barcello_score": "" if barcello_score is None else str(int(barcello_score)),
            "barcello_score_text": score_text,
        }

    def render_moderation_template(self, template: str | None, **context: Any) -> str:
        base = template or ""
        formatted_context = {key: self._format_placeholder_value(key, value) for key, value in context.items()}
        try:
            return base.format(**formatted_context)
        except Exception as exc:  # noqa: BLE001
            return f"[Errore render template: {exc}]\n{base}"

    def compose_final_narrative(
        self,
        *,
        event_type_key: str,
        narrative: str,
        reason_block: str | None,
    ) -> tuple[str, str | None]:
        base_narrative = (narrative or "").strip()
        normalized_reason = self._normalize_reason(reason_block)
        if normalized_reason is None or event_type_key not in _REASON_BLOCK_EVENT_TYPES:
            return base_narrative, None
        return base_narrative, normalized_reason

    def _format_placeholder_value(self, placeholder: str, value: Any) -> Any:
        if value is None:
            return ""
        if placeholder not in _HIGHLIGHTED_PLACEHOLDERS:
            return value
        text = str(value)
        if not text:
            return text
        if placeholder == "reason_suffix":
            stripped = text.strip()
            if not stripped:
                return ""
            leading = text[: len(text) - len(text.lstrip())]
            trailing = text[len(text.rstrip()) :]
            core = stripped
            prefix = ""
            if core.startswith(":"):
                prefix = ":"
                core = core[1:].lstrip()
                if core:
                    prefix += " "
            elif core.startswith("-"):
                prefix = "-"
                core = core[1:].lstrip()
                if core:
                    prefix += " "
            return f"{leading}{prefix}{self._bold_discord_text(core)}{trailing}" if core else f"{leading}{text.strip()}{trailing}"
        return self._bold_discord_text(text)

    @staticmethod
    def _bold_discord_text(value: str) -> str:
        text = value.strip()
        if not text:
            return value
        if text.startswith("**") and text.endswith("**") and len(text) >= 4:
            return value
        leading = value[: len(value) - len(value.lstrip())]
        trailing = value[len(value.rstrip()) :]
        return f"{leading}**{text}**{trailing}"

    async def render_moderation_preview(
        self,
        *,
        template: str | None,
        event_type_key: str,
        user: Any,
        guild: Any,
        moderator: Any | None,
        reason: str | None = None,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
        rejoin_link: str | None = None,
        days_inactive: int | None = None,
        inactivity_text: str | None = None,
        occurrence_number: int = 1,
        mood: str | None = None,
        time_bucket: str | None = None,
        count_tier: str | None = None,
        barcello_color: str | None = None,
        barcello_score: int | None = None,
    ) -> tuple[str, dict[str, Any]]:
        context = self.build_template_context(
            user=user,
            guild=guild,
            event_type_key=event_type_key,
            moderator=moderator,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            rejoin_link=rejoin_link,
            days_inactive=days_inactive,
            inactivity_text=inactivity_text,
            occurrence_number=occurrence_number,
            mood=mood,
            time_bucket=time_bucket,
            count_tier=count_tier,
            barcello_color=barcello_color,
            barcello_score=barcello_score,
        )
        return self.render_moderation_template(template, **context), context

    async def render_event_copy(
        self,
        *,
        guild: Any,
        user: Any,
        event_type_key: str,
        moderator: Any | None = None,
        reason: str | None = None,
        duration_seconds: int | None = None,
        expires_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        channel_id: str | None = None,
        occurrence_number: int | None = None,
        mood: str | None = None,
        barcello_status: dict[str, Any] | None = None,
        now: datetime | None = None,
        reason_block: str | None = None,
    ) -> GreetingsRenderResult:
        self._validate_event_type(event_type_key)
        metadata = metadata or {}
        cfg = self._load_cfg()
        current_now = (now or datetime.now(timezone.utc)).astimezone(ROME_TZ)
        selected_channel_id = channel_id or self._resolve_channel_id(metadata)
        if occurrence_number is None:
            occurrence_number = await self._resolve_occurrence_number(str(getattr(guild, "id", "")), str(getattr(user, "id", "")), event_type_key)
        if barcello_status is None:
            barcello_status = await self._resolve_barcello_status(str(getattr(guild, "id", "")), selected_channel_id)
        normalized_barcello = self.normalize_barcello_state(barcello_status.get("color"))
        barcello_score = self._coerce_int(barcello_status.get("score"))
        selected_mood = mood or self._resolve_mood(cfg)
        time_bucket = self._get_time_bucket(current_now, cfg)
        count_tier = self._get_count_tier(max(1, int(occurrence_number)), cfg)
        moderation_note = self._normalize_reason(reason_block if reason_block is not None else reason)
        context = self.build_template_context(
            user=user,
            guild=guild,
            event_type_key=event_type_key,
            moderator=moderator,
            reason=reason,
            duration_seconds=duration_seconds,
            expires_at=expires_at,
            rejoin_link=str(metadata.get("rejoin_link") or metadata.get("invite_url") or ""),
            days_inactive=self._coerce_int(metadata.get("days_inactive")),
            inactivity_text=str(metadata.get("inactivity_text") or ""),
            occurrence_number=max(1, int(occurrence_number)),
            mood=selected_mood,
            time_bucket=time_bucket,
            count_tier=count_tier,
            barcello_color=normalized_barcello,
            barcello_score=barcello_score,
        )
        if moderation_note and event_type_key in _REASON_BLOCK_EVENT_TYPES:
            context["reason"] = ""
            context["reason_suffix"] = ""

        narrative_template = self._select_narrative_template(
            event_type_key=event_type_key,
            cfg=cfg,
            occurrence_number=max(1, int(occurrence_number)),
            mood=selected_mood,
            time_bucket=time_bucket,
            barcello_state=normalized_barcello,
            count_tier=count_tier,
        )
        narrative, moderation_note = self.compose_final_narrative(
            event_type_key=event_type_key,
            narrative=self._render_narrative_markdown(narrative_template, context=context, event_type_key=event_type_key),
            reason_block=moderation_note,
        )
        return GreetingsRenderResult(
            event_label=format_greetings_event_label(event_type_key, max(1, int(occurrence_number))),
            occurrence_number=max(1, int(occurrence_number)),
            template_context=context,
            narrative=narrative,
            moderation_note=moderation_note,
            mood=selected_mood,
            time_bucket=time_bucket,
            count_tier=count_tier,
            barcello_state=normalized_barcello,
            raw_template=narrative_template,
        )

    def _select_narrative_template(
        self,
        *,
        event_type_key: str,
        cfg: dict[str, Any],
        occurrence_number: int,
        mood: str,
        time_bucket: str,
        barcello_state: str,
        count_tier: str,
    ) -> dict[str, str]:
        contract = cfg.get("event_templates")
        if not isinstance(contract, dict):
            contract = cfg.get("narrative_contract")
        if isinstance(contract, dict):
            event_contract = contract.get(event_type_key)
            selected = self._resolve_contract_variant(event_contract, occurrence_number=occurrence_number)
            if isinstance(selected, dict):
                return self._normalize_narrative_template(selected)

        legacy = self._select_template(
            cfg,
            key=event_type_key,
            mood=mood,
            time_bucket=time_bucket,
            barcello_state=barcello_state,
            count_tier=count_tier,
            occurrence_number=occurrence_number,
        )
        return self._normalize_narrative_template({"event_phrase": legacy})

    def _resolve_contract_variant(self, value: Any, *, occurrence_number: int) -> Any:
        if not isinstance(value, dict):
            return value
        if occurrence_number <= 1 and isinstance(value.get("first_occurrence"), dict):
            return value["first_occurrence"]
        if occurrence_number > 1 and isinstance(value.get("repeat"), dict):
            return value["repeat"]
        if isinstance(value.get("default"), dict):
            return value["default"]
        return value

    def _normalize_narrative_template(self, value: dict[str, Any]) -> dict[str, str]:
        return {
            "opening": str(value.get("opening") or "{mention}"),
            "action_phrase": str(value.get("action_phrase") or value.get("event_phrase") or ""),
            "occurrence_phrase": str(value.get("occurrence_phrase") or ""),
            "detail_phrase": str(value.get("detail_phrase") or ""),
            "barcello_phrase": str(value.get("barcello_phrase") or ""),
            "closing_comment": str(value.get("closing_comment") or ""),
        }

    def _render_narrative_markdown(self, template: dict[str, str], *, context: dict[str, Any], event_type_key: str) -> str:
        main_sentence_parts: list[str] = []
        opening = self.render_moderation_template(template.get("opening"), **context).strip()
        if opening:
            main_sentence_parts.append(self._to_bold_italic(opening))
        action_phrase = self.render_moderation_template(template.get("action_phrase"), **context).strip()
        if action_phrase:
            main_sentence_parts.append(self._to_bold_italic(action_phrase))
        for key in ("occurrence_phrase", "detail_phrase"):
            rendered = self.render_moderation_template(template.get(key), **context).strip()
            if not rendered:
                continue
            main_sentence_parts.append(self._to_italic(rendered))
        body = " ".join(part for part in main_sentence_parts if part).strip()
        segments: list[str] = [body] if body else []

        if event_type_key == "leave":
            barcello_phrase = self.render_moderation_template(template.get("barcello_phrase"), **context).strip()
            if barcello_phrase:
                segments.append(self._to_italic(barcello_phrase))

        closing_comment = self.render_moderation_template(template.get("closing_comment"), **context).strip()
        if closing_comment:
            segments.append(self._to_italic(closing_comment))
        return self._join_narrative_sentences(segments)

    @staticmethod
    def _join_narrative_sentences(segments: list[str]) -> str:
        normalized: list[str] = []
        for segment in segments:
            cleaned = str(segment or "").strip()
            if cleaned:
                normalized.append(cleaned)
        if not normalized:
            return ""

        joined_parts: list[str] = []
        for idx, segment in enumerate(normalized):
            current = segment
            if idx < len(normalized) - 1 and not GreetingsCopyService._has_terminal_sentence_punctuation(current):
                current = f"{current}."
            joined_parts.append(current)
        return " ".join(joined_parts)

    @staticmethod
    def _has_terminal_sentence_punctuation(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        trailing_wrappers = "*_~`\"'”’)]}>"
        stripped = stripped.rstrip(trailing_wrappers).rstrip()
        if not stripped:
            return False
        return stripped[-1] in ".!?"

    @staticmethod
    def _to_italic(text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return ""
        if stripped.startswith("*") and stripped.endswith("*"):
            return stripped
        return f"*{stripped}*"

    @staticmethod
    def _to_bold_italic(text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return ""
        if stripped.startswith("***") and stripped.endswith("***"):
            return stripped
        if stripped.startswith("**") and stripped.endswith("**") and len(stripped) >= 4:
            core = stripped[2:-2].strip()
            return f"***{core}***" if core else stripped
        return f"***{stripped}***"

    async def render_canonical_event_copy(
        self,
        *,
        guild: Any,
        user: Any,
        canonical_event: dict[str, Any],
        moderator: Any | None = None,
        channel_id: str | None = None,
        barcello_status: dict[str, Any] | None = None,
        now: datetime | None = None,
        reason_block: str | None = None,
    ) -> GreetingsRenderResult:
        metadata = canonical_event.get("metadata")
        metadata_dict = metadata if isinstance(metadata, dict) else {}
        expires_at_value = self._parse_event_datetime(canonical_event.get("expires_at"))
        render_reason = self._resolve_canonical_render_reason(canonical_event, metadata_dict)
        return await self.render_event_copy(
            guild=guild,
            user=user,
            event_type_key=str(canonical_event.get("event_type_key") or ""),
            moderator=moderator,
            reason=None,
            reason_block=render_reason,
            duration_seconds=self._coerce_int(canonical_event.get("duration_seconds")),
            expires_at=expires_at_value,
            metadata=metadata_dict,
            channel_id=channel_id,
            occurrence_number=self._resolve_occurrence_from_canonical_event(canonical_event),
            mood=None,
            barcello_status=barcello_status,
            now=now,
        )

    @staticmethod
    def format_duration_human(duration_seconds: int | None) -> str | None:
        if duration_seconds is None:
            return None
        total = max(0, int(duration_seconds))
        days, rem = divmod(total, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        parts: list[str] = []
        if days:
            parts.append(f"{days}g")
        if hours:
            parts.append(f"{hours}h")
        if minutes or not parts:
            parts.append(f"{minutes}m")
        return " ".join(parts)

    def format_barcello_alert_line(self, barcello_color: str | None) -> str:
        normalized = self.normalize_barcello_state(barcello_color)
        return _BARCELLO_ALERTS.get(normalized, "⚪ ALLERTA SCONOSCIUTA")

    def normalize_barcello_state(self, barcello_color: str | None) -> str:
        value = str(barcello_color or "").strip().lower()
        aliases = {
            "green": "verde",
            "yellow": "giallo",
            "red": "rosso",
            "black": "nero",
        }
        return aliases.get(value, value or "unknown")

    def _format_barcello_score(self, barcello_score: int | None) -> str:
        return "n/d" if barcello_score is None else f"{int(barcello_score)}/100"

    def _resolve_canonical_render_reason(self, canonical_event: dict[str, Any], metadata: dict[str, Any]) -> str | None:
        if "greetings_reason" in metadata:
            return self._normalize_reason(metadata.get("greetings_reason"))
        return self._normalize_reason(canonical_event.get("reason"))

    @staticmethod
    def _normalize_reason(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    def _load_cfg(self) -> dict[str, Any]:
        loaded = load_json_file(self._config_path, example_path=GREETINGS_TRIGGER_EXAMPLE_JSON)
        if not loaded:
            return self._deep_merge(_DEFAULT_GREETINGS_TRIGGER, {})
        return self._deep_merge(_DEFAULT_GREETINGS_TRIGGER, loaded)


    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for key in set(base) | set(override):
            base_value = base.get(key)
            override_value = override.get(key)
            if isinstance(base_value, dict) and isinstance(override_value, dict):
                merged[key] = self._deep_merge(base_value, override_value)
            elif key in override:
                merged[key] = override_value
            else:
                merged[key] = base_value
        return merged

    def _resolve_mood(self, cfg: dict[str, Any]) -> str:
        mood = cfg.get("mood_default")
        return str(mood) if isinstance(mood, str) and mood.strip() else str(_DEFAULT_GREETINGS_TRIGGER["mood_default"])

    def _get_time_bucket(self, now_rome: datetime, cfg: dict[str, Any]) -> str:
        default_buckets = _DEFAULT_GREETINGS_TRIGGER["time_buckets"]
        buckets = cfg.get("time_buckets") if isinstance(cfg.get("time_buckets"), dict) else default_buckets
        hour = now_rome.hour
        for name, payload in buckets.items():
            if not isinstance(payload, dict):
                continue
            start = payload.get("start")
            end = payload.get("end")
            if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= 24 and start <= hour < end:
                return str(name)
        if buckets:
            return str(next(iter(buckets.keys())))
        return "unknown"

    def _get_count_tier(self, occurrence_number: int, cfg: dict[str, Any]) -> str:
        raw_tiers = cfg.get("count_tiers")
        tiers = raw_tiers if isinstance(raw_tiers, list) else _DEFAULT_GREETINGS_TRIGGER["count_tiers"]
        winner = "t1"
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            minimum = tier.get("min_occurrence")
            label = tier.get("label")
            if isinstance(minimum, int) and isinstance(label, str) and occurrence_number >= minimum:
                winner = label
        return winner

    def _select_template(
        self,
        cfg: dict[str, Any],
        *,
        key: str,
        mood: str,
        time_bucket: str,
        barcello_state: str,
        count_tier: str,
        occurrence_number: int,
    ) -> str:
        moods = cfg.get("moods") if isinstance(cfg.get("moods"), dict) else {}
        mood_cfg = moods.get(mood) if isinstance(moods.get(mood), dict) else None
        candidates: list[object] = []
        candidates.extend(self._collect_candidates(mood_cfg, key=key, time_bucket=time_bucket, barcello_state=barcello_state, count_tier=count_tier))
        candidates.extend(self._collect_candidates(cfg, key=key, time_bucket=time_bucket, barcello_state=barcello_state, count_tier=count_tier))
        defaults_cfg = cfg.get("defaults") if isinstance(cfg.get("defaults"), dict) else {}
        fallback_cfg = defaults_cfg.get("fallbacks") if isinstance(defaults_cfg.get("fallbacks"), dict) else {}
        candidates.append(fallback_cfg.get(key))
        for candidate in candidates:
            selected = self._resolve_template_value(
                candidate,
                seed_parts=(key, mood, time_bucket, barcello_state, count_tier, str(occurrence_number)),
                occurrence_number=occurrence_number,
            )
            if selected:
                return selected
        fallback = _DEFAULT_GREETINGS_TRIGGER["defaults"]["fallbacks"].get(key)
        return self._resolve_template_value(
            fallback,
            seed_parts=(key, "default", time_bucket, barcello_state, count_tier, str(occurrence_number)),
            occurrence_number=occurrence_number,
        )

    def _collect_candidates(
        self,
        base: object,
        *,
        key: str,
        time_bucket: str,
        barcello_state: str,
        count_tier: str,
    ) -> list[object]:
        if not isinstance(base, dict):
            return []
        candidates: list[object] = []
        templates = base.get("templates") if isinstance(base.get("templates"), dict) else {}
        time_cfg = base.get("time") if isinstance(base.get("time"), dict) else {}
        barcello_cfg = base.get("barcello") if isinstance(base.get("barcello"), dict) else {}
        count_cfg = base.get("count") if isinstance(base.get("count"), dict) else {}

        selected_time = time_cfg.get(time_bucket) if isinstance(time_cfg.get(time_bucket), dict) else {}
        selected_barcello = barcello_cfg.get(barcello_state) if isinstance(barcello_cfg.get(barcello_state), dict) else {}
        selected_count = count_cfg.get(count_tier) if isinstance(count_cfg.get(count_tier), dict) else {}

        time_templates = selected_time.get("templates") if isinstance(selected_time.get("templates"), dict) else {}
        barcello_templates = selected_barcello.get("templates") if isinstance(selected_barcello.get("templates"), dict) else {}
        count_templates = selected_count.get("templates") if isinstance(selected_count.get("templates"), dict) else {}

        time_barcello = selected_time.get("barcello") if isinstance(selected_time.get("barcello"), dict) else {}
        time_count = selected_time.get("count") if isinstance(selected_time.get("count"), dict) else {}
        barcello_count = selected_barcello.get("count") if isinstance(selected_barcello.get("count"), dict) else {}

        time_barcello_cfg = time_barcello.get(barcello_state) if isinstance(time_barcello.get(barcello_state), dict) else {}
        time_count_cfg = time_count.get(count_tier) if isinstance(time_count.get(count_tier), dict) else {}
        barcello_count_cfg = barcello_count.get(count_tier) if isinstance(barcello_count.get(count_tier), dict) else {}

        time_barcello_templates = (
            time_barcello_cfg.get("templates") if isinstance(time_barcello_cfg.get("templates"), dict) else {}
        )
        time_count_templates = time_count_cfg.get("templates") if isinstance(time_count_cfg.get("templates"), dict) else {}
        barcello_count_templates = (
            barcello_count_cfg.get("templates") if isinstance(barcello_count_cfg.get("templates"), dict) else {}
        )

        nested_combo_templates: dict[str, Any] = {}
        nested_combo = time_barcello_cfg.get("count") if isinstance(time_barcello_cfg.get("count"), dict) else {}
        if isinstance(nested_combo.get(count_tier), dict):
            nested_combo_templates = (
                nested_combo.get(count_tier).get("templates")
                if isinstance(nested_combo.get(count_tier).get("templates"), dict)
                else {}
            )

        candidates.append(nested_combo_templates.get(key))
        candidates.append(time_barcello_templates.get(key))
        candidates.append(time_count_templates.get(key))
        candidates.append(barcello_count_templates.get(key))
        candidates.append(count_templates.get(key))
        candidates.append(time_templates.get(key))
        candidates.append(barcello_templates.get(key))
        candidates.append(templates.get(key))
        return candidates

    def _resolve_template_value(self, value: object, *, seed_parts: tuple[str, ...], occurrence_number: int) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            options = [item.strip() for item in value if isinstance(item, str) and item.strip()]
            if not options:
                return ""
            seed = "|".join(seed_parts)
            hashed = hashlib.sha256(seed.encode("utf-8")).hexdigest()
            return options[int(hashed[:8], 16) % len(options)]
        if isinstance(value, dict):
            variant_order: list[str]
            if max(1, int(occurrence_number)) == 1:
                variant_order = ["first_occurrence", "first_time", "welcome", "default", "fallback", "all"]
            else:
                variant_order = ["repeat", "returning", "reentry", "default", "fallback", "all"]
            for variant_key in variant_order:
                selected = self._resolve_template_value(
                    value.get(variant_key),
                    seed_parts=seed_parts + (variant_key,),
                    occurrence_number=occurrence_number,
                )
                if selected:
                    return selected
            templates_value = value.get("templates")
            if templates_value is not None:
                return self._resolve_template_value(
                    templates_value,
                    seed_parts=seed_parts + ("templates",),
                    occurrence_number=occurrence_number,
                )
        return ""

    async def _resolve_occurrence_number(self, guild_id: str, user_id: str, event_type_key: str) -> int:
        if not guild_id or not user_id or self._database is None or not hasattr(self._database, "count_member_flow_events_for_user"):
            return 1
        try:
            total = await self._database.count_member_flow_events_for_user(guild_id, user_id, event_type_key)
        except Exception:  # noqa: BLE001
            logger.warning("greetings occurrence count failed guild=%s user=%s event=%s", guild_id, user_id, event_type_key, exc_info=True)
            return 1
        return max(1, int(total or 0))

    async def _resolve_barcello_status(self, guild_id: str, channel_id: str | None) -> dict[str, Any]:
        if self._barcello_service is None or not guild_id or not channel_id:
            return {"color": None, "score": None}
        try:
            status = await self._barcello_service.get_current_status(guild_id, channel_id=str(channel_id))
        except Exception:  # noqa: BLE001
            logger.warning("greetings barcello lookup failed guild=%s channel=%s", guild_id, channel_id, exc_info=True)
            return {"color": None, "score": None}
        if not isinstance(status, dict):
            return {"color": None, "score": None}
        return {"color": status.get("color"), "score": self._coerce_int(status.get("score"))}

    def _resolve_channel_id(self, metadata: dict[str, Any]) -> str | None:
        for key in ("channel_id", "notify_channel_id", "atrio_channel_id"):
            value = metadata.get(key)
            if value is not None and str(value).strip():
                return str(value)
        return None

    def _resolve_occurrence_from_canonical_event(self, canonical_event: dict[str, Any]) -> int | None:
        occurrence = self._coerce_int(canonical_event.get("occurrence_number"))
        if occurrence is not None:
            return max(1, occurrence)
        metadata = canonical_event.get("metadata")
        if isinstance(metadata, dict):
            metadata_occurrence = self._coerce_int(metadata.get("occurrence_number"))
            if metadata_occurrence is not None:
                return max(1, metadata_occurrence)
        return None

    def _parse_event_datetime(self, value: Any) -> datetime | None:
        raw = self._as_optional_str(value)
        if raw is None:
            return None
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _as_optional_str(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _event_label_text(self, event_type_key: str) -> str:
        self._validate_event_type(event_type_key)
        return _EVENT_LABELS[event_type_key][1]

    def _validate_event_type(self, event_type_key: str) -> None:
        if event_type_key not in SUPPORTED_GREETINGS_EVENT_TYPES:
            raise ValueError(f"Unsupported greetings event type: {event_type_key}")

    def _format_ordinal_upper(self, event_type_key: str, occurrence_number: int) -> str:
        gender = _EVENT_LABELS[event_type_key][2]
        occurrence = max(1, int(occurrence_number))
        mapping = _ORDINALS_UPPER_FEMININE if gender == "f" else _ORDINALS_UPPER_MASCULINE
        if occurrence in mapping:
            return mapping[occurrence]
        return f"{occurrence}{'ª' if gender == 'f' else '°'}"

    def _coerce_int(self, value: Any) -> int | None:
        try:
            return None if value is None or value == "" else int(value)
        except Exception:  # noqa: BLE001
            return None


def format_greetings_event_label(event_type_key: str, occurrence_number: int) -> str:
    return build_greetings_title(event_type_key, occurrence_number)


def build_greetings_title(event_type_key: str, occurrence_count: int, is_auto_inactivity: bool = False) -> str:
    normalized = str(event_type_key or "").strip().lower()
    occurrence = max(1, int(occurrence_count))
    if is_auto_inactivity and normalized == "tempban":
        normalized = "inactive_tempban"
    title_map: dict[str, tuple[str, str, str]] = {
        "leave": ("👋", "PRIMA USCITA", "RIUSCITA"),
        "join": ("🤝", "PRIMA ENTRATA", "RIENTRATA"),
        "kick": ("👢", "PRIMA ESPULSIONE", "ALTRA ESPULSIONE"),
        "inactive_kick": ("👢", "PRIMA ESPULSIONE", "ALTRA ESPULSIONE"),
        "ban": ("⛔", "PRIMA INTERDIZIONE PERENNE", "ALTRA INTERDIZIONE PERENNE"),
        "tempban": ("⌛", "PRIMA INTERDIZIONE TEMPORANEA", "ALTRA INTERDIZIONE TEMPORANEA"),
        "inactive_tempban": ("⌛", "PRIMA INTERDIZIONE TEMPORANEA", "ALTRA INTERDIZIONE TEMPORANEA"),
        "grace": ("🕊️", "PRIMA GRAZIA", "ALTRA GRAZIA"),
        "inactive_grace": ("🕊️", "PRIMA GRAZIA", "ALTRA GRAZIA"),
    }
    if normalized not in title_map:
        raise ValueError(f"Unsupported greetings event type: {event_type_key}")
    emoji, first, repeat = title_map[normalized]
    text = first if occurrence == 1 else repeat
    return f"{emoji} __**{text}**__"
