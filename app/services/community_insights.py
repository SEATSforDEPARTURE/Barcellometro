from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.ai import AiService

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = "Sapevate che {user_name} ama {hobby}? L'ha detto il {dt}. {jump_url}"
DEFAULT_INTERVAL_MINUTES = 180


class CommunityInsightsService:
    def __init__(self, ai_service: AiService | None = None) -> None:
        self._ai_service = ai_service

    async def parse_config_prompt(self, text: str) -> dict[str, Any]:
        defaults = {
            "interval_minutes": DEFAULT_INTERVAL_MINUTES,
            "template": DEFAULT_TEMPLATE,
            "channel_scope": "current",
        }
        if not text.strip():
            return defaults

        parsed = self._extract_config_heuristic(text)
        ai_data = await self._extract_config_ai(text)
        if ai_data:
            parsed.update(ai_data)

        interval = int(parsed.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES)
        parsed["interval_minutes"] = max(10, interval)
        template = str(parsed.get("template") or DEFAULT_TEMPLATE).strip()
        parsed["template"] = template or DEFAULT_TEMPLATE
        scope = str(parsed.get("channel_scope") or "current").strip().lower()
        parsed["channel_scope"] = "current" if scope not in {"current", "guild"} else scope
        return parsed

    async def get_config(self, raw_setting: Optional[str]) -> dict[str, Any]:
        if raw_setting:
            try:
                loaded = json.loads(raw_setting)
            except json.JSONDecodeError:
                loaded = {}
        else:
            loaded = {}
        if not isinstance(loaded, dict):
            loaded = {}
        return {
            "interval_minutes": int(loaded.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES),
            "template": str(loaded.get("template") or DEFAULT_TEMPLATE),
            "channel_scope": str(loaded.get("channel_scope") or "current"),
        }

    def extract_hobbies_from_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        hobbies: list[dict[str, str]] = []
        patterns = [
            r"\b(?:mi piace|amo|adoro|passione|hobby|nel tempo libero)\b([^.!?]{2,80})",
        ]
        for msg in messages:
            content = str(msg.get("content") or "").strip()
            if not content:
                continue
            normalized = content.lower()
            for pattern in patterns:
                match = re.search(pattern, normalized, flags=re.IGNORECASE)
                if not match:
                    continue
                hobby = re.sub(r"[^\w\sàèéìòù]", " ", match.group(1)).strip()
                hobby = re.sub(r"\s+", " ", hobby)
                if not hobby:
                    continue
                hobbies.append(
                    {
                        "guild_id": str(msg.get("guild_id") or ""),
                        "user_id": str(msg.get("author_id") or ""),
                        "user_name": str(msg.get("user_name") or msg.get("author_id") or "utente"),
                        "hobby": hobby[:80],
                        "source_channel_id": str(msg.get("channel_id") or ""),
                        "source_message_id": str(msg.get("message_id") or ""),
                        "source_created_at": str(msg.get("ts") or datetime.now(timezone.utc).isoformat()),
                    }
                )
                break
        return hobbies

    async def extract_hobbies_ai(self, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        if self._ai_service is None or not self._ai_service.is_enabled() or self._ai_service.client() is None:
            return []
        small_batch = [
            {
                "user_id": str(m.get("author_id") or ""),
                "user_name": str(m.get("user_name") or ""),
                "message_id": str(m.get("message_id") or ""),
                "created_at": str(m.get("ts") or ""),
                "text": str(m.get("content") or "")[:200],
            }
            for m in messages[:20]
        ]
        payload = json.dumps(
            {
                "task": "extract_user_hobbies",
                "rules": ["Rispondi solo con JSON valido.", "Estrai solo hobby/curiosità realmente espliciti."],
                "messages": small_batch,
                "output_schema": [
                    {"user_id": "string", "user_name": "string", "hobby": "string", "message_id": "string", "created_at": "string"}
                ],
            },
            ensure_ascii=False,
        )
        try:
            response = await self._ai_service.client().responses.create(
                model=self._ai_service.get_model("summary") or "gpt-4o-mini",
                input=payload,
            )
        except Exception:
            logger.exception("Community insights AI extraction failed")
            return []
        try:
            parsed = json.loads(getattr(response, "output_text", "") or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        out: list[dict[str, str]] = []
        message_meta = {str(m.get("message_id")): m for m in messages}
        for item in parsed:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("message_id") or "")
            meta = message_meta.get(message_id, {})
            hobby = str(item.get("hobby") or "").strip()
            if not hobby:
                continue
            out.append(
                {
                    "guild_id": str(meta.get("guild_id") or ""),
                    "user_id": str(item.get("user_id") or meta.get("author_id") or ""),
                    "user_name": str(item.get("user_name") or meta.get("user_name") or "utente"),
                    "hobby": hobby[:80],
                    "source_channel_id": str(meta.get("channel_id") or ""),
                    "source_message_id": message_id,
                    "source_created_at": str(item.get("created_at") or meta.get("ts") or datetime.now(timezone.utc).isoformat()),
                }
            )
        return out

    async def get_next_message(self, guild_id: str) -> Optional[str]:
        _ = guild_id
        return None

    def render_template(self, template: str, values: dict[str, str]) -> str:
        output = template
        for key, value in values.items():
            output = output.replace("{" + key + "}", value)
        return output

    def status(self, enabled: bool, config: dict[str, Any], last_post_at: str | None) -> dict[str, object]:
        return {
            "active": True,
            "enabled": enabled,
            "interval_minutes": int(config.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES),
            "template": str(config.get("template") or DEFAULT_TEMPLATE),
            "last_post_at": last_post_at,
        }

    def _extract_config_heuristic(self, text: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "interval_minutes": DEFAULT_INTERVAL_MINUTES,
            "template": DEFAULT_TEMPLATE,
            "channel_scope": "current",
        }
        interval_match = re.search(r"ogni\s+(\d{1,4})\s+min", text, flags=re.IGNORECASE)
        if interval_match:
            result["interval_minutes"] = int(interval_match.group(1))
        return result

    async def _extract_config_ai(self, text: str) -> Optional[dict[str, Any]]:
        if self._ai_service is None or not self._ai_service.is_enabled() or self._ai_service.client() is None:
            return None
        payload = json.dumps(
            {
                "task": "community_insights_config",
                "instruction": text,
                "reply_only_json": True,
                "output_schema": {
                    "interval_minutes": 120,
                    "template": "Sapevate che {user_name} ama {hobby}? L'ha detto il {dt}. {jump_url}",
                    "channel_scope": "current",
                },
            },
            ensure_ascii=False,
        )
        try:
            response = await self._ai_service.client().responses.create(
                model=self._ai_service.get_model("summary") or "gpt-4o-mini",
                input=payload,
            )
        except Exception:
            logger.exception("Community insights config parse failed")
            return None
        try:
            parsed = json.loads(getattr(response, "output_text", "") or "{}")
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
