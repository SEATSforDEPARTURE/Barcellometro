from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

import discord

from app.services.ai import AiService
from app.services.campaign_content_fetchers import fetch_horoscope_content, fetch_news_content, fetch_weather_content
from app.services.campaign_content_formatter import (
    apply_shared_footer_and_pagination,
    build_fallback_embed,
    build_horoscope_embeds,
    build_news_embeds,
    build_weather_embeds,
)
from app.services.campaign_content_views import CampaignContentPaginationView, HoroscopePaginationView
from app.services.database import DatabaseService
from app.services.footer import FooterService, attach_footer_meta_to_all
from app.services.scheduler_utils import calculate_next_run_after_send

logger = logging.getLogger(__name__)


class CampaignContentService:
    def __init__(self, database: DatabaseService, bot: discord.Client, ai_service: Optional[AiService] = None) -> None:
        self._database = database
        self._bot = bot
        self._ai = ai_service
        self._footer = FooterService(database)
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
        configured_sources = self._normalize_sources(self._json_to_list(config.get("sources_json")))
        payload = fetch_news_content(configured_sources, categories)
        used_sources = self._normalize_sources(payload.get("used_sources", []))
        used_model: str | None = None
        fallback_used = False
        if not payload.get("categories"):
            fallback_used = True
            embeds = build_fallback_embed(config, payload.get("sources", []))
        else:
            used_model = await self._rewrite_news_payload(payload)
            embeds = build_news_embeds(config, payload)
        await self._send_and_store(
            config,
            embeds,
            "NEWS",
            configured_sources=configured_sources,
            used_sources=used_sources,
            used_model=used_model,
            fallback_used=fallback_used,
        )

    async def execute_weather_service(self, config: dict[str, Any]) -> None:
        configured_sources = self._normalize_sources(self._json_to_list(config.get("sources_json")))
        payload = fetch_weather_content(configured_sources)
        used_model = await self._rewrite_weather_payload(payload)
        used_sources = self._normalize_sources(payload.get("used_sources", []))
        embeds = build_weather_embeds(config, payload)
        await self._send_and_store(
            config,
            embeds,
            "WEATHER",
            configured_sources=configured_sources,
            used_sources=used_sources,
            used_model=used_model,
            fallback_used=bool(payload.get("fallback_used")),
        )

    async def execute_horoscope_service(self, config: dict[str, Any]) -> None:
        configured_sources = self._normalize_sources(self._json_to_list(config.get("sources_json")))
        payload = fetch_horoscope_content(configured_sources)
        used_model = await self._rewrite_horoscope_payload(payload)
        used_sources = self._normalize_sources(payload.get("used_sources", []))
        embeds = build_horoscope_embeds(config, payload)
        await self._send_and_store(
            config,
            embeds,
            "HOROSCOPE",
            configured_sources=configured_sources,
            used_sources=used_sources,
            used_model=used_model,
            fallback_used=bool(payload.get("fallback_used")),
        )

    async def _send_and_store(
        self,
        config: dict[str, Any],
        embeds: list[discord.Embed],
        service_type: str,
        *,
        configured_sources: list[str],
        used_sources: list[str],
        used_model: str | None,
        fallback_used: bool,
    ) -> None:
        now = datetime.now(timezone.utc)
        guild_id = str(config["guild_id"])
        channel_id = str(config["channel_id"])
        footer_sources = used_sources or configured_sources
        footer_text = await self._build_campaign_footer(used_sources=footer_sources, used_model=used_model)
        contributors = [*footer_sources, *([used_model] if used_model else [])]
        attach_footer_meta_to_all(
            embeds,
            service_name="campagne",
            contributors=contributors,
            used_local_processing=not contributors,
        )
        apply_shared_footer_and_pagination(embeds, footer_text)
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
        metadata = {
            "footer_text": footer_text,
            "configured_sources": configured_sources,
            "used_sources": used_sources,
            "ai_model_used": used_model,
            "used_model": used_model,
            "fallback_used": fallback_used,
        }
        await self._database.upsert_campaign_content_message(
            message_id=str(message.id),
            guild_id=guild_id,
            channel_id=channel_id,
            service_type=service_type,
            config_id=int(config["id"]),
            embeds_json=json.dumps([e.to_dict() for e in embeds], ensure_ascii=False),
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            current_index=0,
        )
        next_run = calculate_next_run_after_send(now, int(config["interval_minutes"]), 0)
        await self._database.update_campaign_content_next_run(guild_id=guild_id, config_id=int(config["id"]), next_run_at=next_run.isoformat(), last_sent_at=now.isoformat())

    async def _rewrite_news_payload(self, payload: dict[str, Any]) -> str | None:
        used_ai = False
        for items in payload.get("categories", {}).values():
            for item in items[:5]:
                rewritten, ai_used = await self._rewrite_text(
                    item.get("summary", ""),
                    context="notizie",
                    extra=[item.get("title", ""), item.get("category", "")],
                )
                item["summary"] = rewritten
                used_ai = used_ai or ai_used
        return self._resolve_ai_model_name() if used_ai else None

    async def _rewrite_weather_payload(self, payload: dict[str, Any]) -> str | None:
        used_ai = False
        for region in payload.get("regions", {}).values():
            summary = str(region.get("summary") or "")
            rewritten, ai_used = await self._rewrite_text(
                summary,
                context="meteo",
                extra=region.get("source_points", []),
            )
            region["summary"] = rewritten
            used_ai = used_ai or ai_used
        return self._resolve_ai_model_name() if used_ai else None

    async def _rewrite_horoscope_payload(self, payload: dict[str, Any]) -> str | None:
        used_ai = False
        for sign_payload in payload.get("signs", {}).values():
            sign = sign_payload.get("sign") or "segno"
            for key in ["love", "work", "money", "energy", "friction", "advice"]:
                rewritten, ai_used = await self._rewrite_text(
                    str(sign_payload.get(key) or ""),
                    context="oroscopo",
                    extra=[str(sign), key],
                )
                sign_payload[key] = rewritten
                used_ai = used_ai or ai_used
        self._enforce_horoscope_diversity(payload)
        return self._resolve_ai_model_name() if used_ai else None

    @staticmethod
    def _simple_similarity(a: str, b: str) -> float:
        tokens_a = {token for token in re.findall(r"\w+", a.lower()) if len(token) > 3}
        tokens_b = {token for token in re.findall(r"\w+", b.lower()) if len(token) > 3}
        if not tokens_a or not tokens_b:
            return 0.0
        return len(tokens_a.intersection(tokens_b)) / max(1, len(tokens_a.union(tokens_b)))

    def _enforce_horoscope_diversity(self, payload: dict[str, Any]) -> None:
        signs = payload.get("signs", {})
        rendered: dict[str, str] = {}
        for sign, sign_payload in signs.items():
            combined = " ".join(str(sign_payload.get(k) or "") for k in ["love", "work", "money", "energy", "friction", "advice"])
            for seen_sign, seen_text in rendered.items():
                if self._simple_similarity(combined, seen_text) >= 0.78:
                    sign_payload["advice"] = f"Versione personalizzata per {sign}: {sign_payload.get('advice', '')}".strip()
                    sign_payload["friction"] = f"{sign_payload.get('friction', '')} (dinamica diversa da {seen_sign})".strip()
                    combined = " ".join(str(sign_payload.get(k) or "") for k in ["love", "work", "money", "energy", "friction", "advice"])
                    break
            rendered[sign] = combined

    async def _rewrite_text(self, text: str, *, context: str, extra: list[str] | None = None) -> tuple[str, bool]:
        if not text:
            return text, False
        if self._ai is None or not self._ai.is_enabled():
            return text, False
        extra_info = " | ".join(x for x in (extra or []) if x)
        prompt = (
            f"Servizio: {context}. Riscrivi in italiano per Discord con tono leggero e ironico ma sostanzioso. "
            "Non inventare dati/fatti/valori e non cambiare numeri. Evita frasi generiche fotocopia. "
            f"Contesto: {extra_info}.\nTesto:\n{text}"
        )
        output = await self._ai.ask_general(prompt, "Assistente editoriale")
        return (output or text).strip(), True

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

    async def _build_campaign_footer(self, *, used_sources: list[str], used_model: str | None) -> str:
        contributors = list(used_sources)
        model = (used_model or "").strip()
        if model and model not in contributors:
            contributors.append(model)
        text, _ = await self._footer.render_footer(
            service_name="campagne",
            contributors=contributors,
            used_local_processing=not contributors,
        )
        await self._footer.record_service_footer_profile(
            service_name="campagne",
            contributors=contributors,
            used_local_processing=not contributors,
            last_rendered_footer=text,
            origin="runtime",
        )
        return text

    @staticmethod
    def _normalize_sources(sources: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for source in sources:
            token = str(source or "").strip().lower()
            if not token or token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized

    def _resolve_ai_model_name(self) -> str:
        if self._ai is not None:
            model = self._ai.get_model("summary")
            if isinstance(model, str) and model.strip():
                return model.strip()
        return "gpt-4o"
