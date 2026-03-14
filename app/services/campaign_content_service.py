from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import discord

from app.services.ai import AiService
from app.services.campaign_content_fetchers import fetch_horoscope_content, fetch_news_content, fetch_weather_content
from app.services.campaign_content_formatter import (
    build_fallback_embed,
    build_horoscope_embeds,
    build_news_embeds,
    build_weather_embeds,
)
from app.services.campaign_content_views import CampaignContentPaginationView, HoroscopePaginationView
from app.services.database import DatabaseService
from app.services.scheduler_utils import calculate_next_run_after_send

logger = logging.getLogger(__name__)


class CampaignContentService:
    def __init__(self, database: DatabaseService, bot: discord.Client, ai_service: Optional[AiService] = None) -> None:
        self._database = database
        self._bot = bot
        self._ai = ai_service
        self._registered = False

    def register_views(self) -> None:
        if self._registered:
            return
        self._bot.add_view(CampaignContentPaginationView(self))
        self._bot.add_view(HoroscopePaginationView(self))
        self._registered = True

    async def process_due_services(self, now: datetime) -> None:
        rows = await self._database.due_campaign_content_configs(now.isoformat())
        for config in rows:
            service_type = str(config.get("service_type") or "").upper()
            if service_type == "NEWS":
                await self.execute_news_service(config)
            elif service_type == "WEATHER":
                await self.execute_weather_service(config)
            elif service_type == "HOROSCOPE":
                await self.execute_horoscope_service(config)

    async def execute_news_service(self, config: dict[str, Any]) -> None:
        categories = self._csv_to_list(config.get("categories_json"))
        sources = self._json_to_list(config.get("sources_json"))
        payload = fetch_news_content(sources, categories)
        if not payload.get("categories"):
            embeds = build_fallback_embed(config, payload.get("sources", []))
        else:
            await self._rewrite_news_payload(payload)
            embeds = build_news_embeds(config, payload)
        await self._send_and_store(config, embeds, "NEWS")

    async def execute_weather_service(self, config: dict[str, Any]) -> None:
        sources = self._json_to_list(config.get("sources_json"))
        payload = fetch_weather_content(sources)
        embeds = build_weather_embeds(config, payload)
        await self._send_and_store(config, embeds, "WEATHER")

    async def execute_horoscope_service(self, config: dict[str, Any]) -> None:
        sources = self._json_to_list(config.get("sources_json"))
        payload = fetch_horoscope_content(sources)
        await self._rewrite_horoscope_payload(payload)
        embeds = build_horoscope_embeds(config, payload)
        await self._send_and_store(config, embeds, "HOROSCOPE")

    async def _send_and_store(self, config: dict[str, Any], embeds: list[discord.Embed], service_type: str) -> None:
        now = datetime.now(timezone.utc)
        guild_id = str(config["guild_id"])
        channel_id = str(config["channel_id"])
        channel = self._bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self._bot.fetch_channel(int(channel_id))
            except Exception:
                logger.exception("campaign content: channel resolve failed")
                return
        if not isinstance(channel, discord.abc.Messageable):
            return
        view: discord.ui.View | None = None
        if service_type in {"NEWS", "WEATHER"}:
            view = CampaignContentPaginationView(self, current_index=0, total_pages=len(embeds))
        elif service_type == "HOROSCOPE":
            view = HoroscopePaginationView(self)
        message = await channel.send(embed=embeds[0], view=view)
        await self._database.upsert_campaign_content_message(
            message_id=str(message.id),
            guild_id=guild_id,
            channel_id=channel_id,
            service_type=service_type,
            config_id=int(config["id"]),
            embeds_json=json.dumps([e.to_dict() for e in embeds], ensure_ascii=False),
            metadata_json=json.dumps({}, ensure_ascii=False),
            current_index=0,
        )
        next_run = calculate_next_run_after_send(now, int(config["interval_minutes"]), 0)
        await self._database.update_campaign_content_next_run(guild_id=guild_id, config_id=int(config["id"]), next_run_at=next_run.isoformat(), last_sent_at=now.isoformat())

    async def _rewrite_news_payload(self, payload: dict[str, Any]) -> None:
        for items in payload.get("categories", {}).values():
            for item in items[:5]:
                item["summary"] = await self._rewrite_text(item.get("summary", ""))

    async def _rewrite_horoscope_payload(self, payload: dict[str, Any]) -> None:
        for sign_payload in payload.get("signs", {}).values():
            sign_payload["text"] = await self._rewrite_text(sign_payload.get("text", ""))

    async def _rewrite_text(self, text: str) -> str:
        if not text:
            return text
        if self._ai is None or not self._ai.is_enabled():
            return text
        prompt = (
            "Riscrivi senza inventare dati, tono simpatico ironico semplice per cricetine/polle, frasi brevi:\n"
            f"{text}"
        )
        output = await self._ai.ask_general(prompt, "Assistente editoriale")
        return (output or text).strip()

    async def load_message_record(self, message_id: str) -> dict[str, Any] | None:
        row = await self._database.get_campaign_content_message(message_id)
        if row is None:
            return None
        return {
            "embeds": json.loads(str(row["embeds_json"] or "[]")),
            "current_index": int(row["current_index"] or 0),
        }

    async def persist_current_index(self, message_id: str, current_index: int) -> None:
        await self._database.update_campaign_content_current_index(message_id, current_index)

    @staticmethod
    def _json_to_list(raw: Any) -> list[str]:
        if raw is None:
            return []
        try:
            payload = json.loads(str(raw))
            if isinstance(payload, list):
                return [str(x) for x in payload]
        except json.JSONDecodeError:
            pass
        return []

    @staticmethod
    def _csv_to_list(raw: Any) -> list[str]:
        if not raw:
            return []
        value = str(raw).strip()
        if value.startswith("["):
            try:
                payload = json.loads(value)
                if isinstance(payload, list):
                    return [str(x) for x in payload]
            except json.JSONDecodeError:
                return []
        return [v.strip() for v in value.split(",") if v.strip()]
