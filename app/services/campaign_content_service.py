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
    HOROSCOPE_SECTIONS,
    SIGN_ORDER,
    apply_shared_footer_and_pagination,
    build_fallback_embed,
    build_horoscope_embeds,
    build_horoscope_page_map,
    build_news_embeds,
    build_news_page_map,
    build_weather_embeds,
    build_weather_page_map,
    sanitize_horoscope_text,
)
from app.services.campaign_content_views import BaseCampaignNavigatorView, PersistentCampaignLauncherView
from app.services.database import DatabaseService
from app.services.footer import FooterService, attach_footer_meta
from app.services.footer import attach_footer_meta_to_all
from app.utils.component_notices import send_standard_component_notice
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
        # Dynamic persistent views are re-created per message from DB metadata.
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
            payload=payload,
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
            payload=payload,
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
            payload=payload,
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
        payload: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        guild_id = str(config["guild_id"])
        channel_id = str(config["channel_id"])
        footer_sources = used_sources or configured_sources
        footer_service_name = self._campaign_footer_service_name(service_type)
        footer_text = await self._build_campaign_footer(service_name=footer_service_name, used_sources=footer_sources, used_model=used_model)
        contributors = [*footer_sources, *([used_model] if used_model else [])]
        attach_footer_meta_to_all(
            embeds,
            service_name=footer_service_name,
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
        page_map = self._build_page_map(service_type, payload_embeds=embeds, payload=payload)
        view: discord.ui.View | None = PersistentCampaignLauncherView(
            self,
            service_type=service_type,
            total_pages=len(embeds),
            page_map=page_map,
        )
        message = await channel.send(embed=embeds[0], view=view)
        metadata = {
            "footer_text": footer_text,
            "configured_sources": configured_sources,
            "used_sources": used_sources,
            "ai_model_used": used_model,
            "used_model": used_model,
            "fallback_used": fallback_used,
            "page_map": page_map,
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
        interval_minutes = int(config.get("interval_minutes") or 0)
        if interval_minutes <= 0:
            await self._database.update_campaign_content_next_run(guild_id=guild_id, config_id=int(config["id"]), next_run_at=now.isoformat(), last_sent_at=now.isoformat())
            await self._database.set_campaign_content_enabled(guild_id=guild_id, config_id=int(config["id"]), enabled=False)
            return
        next_run = calculate_next_run_after_send(now, interval_minutes, 0)
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
        return self._resolve_ai_model_name("campaign_editorial") if used_ai else None

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
        return self._resolve_ai_model_name("campaign_editorial") if used_ai else None

    async def _rewrite_horoscope_payload(self, payload: dict[str, Any]) -> str | None:
        if self._ai is None or not self._ai.is_enabled():
            self._enforce_horoscope_diversity(payload)
            return None
        signs = payload.get("signs", {})
        compact = {
            sign: {section: str(sign_payload.get(section) or "") for section in HOROSCOPE_SECTIONS}
            for sign, sign_payload in signs.items()
        }
        prompt = (
            "Riscrivi il seguente JSON oroscopo in italiano con tono ironico/cricetoso ma leggibile. "
            "Devi restituire SOLO JSON valido con la stessa struttura in input. "
            "Non inventare fatti, non aggiungere markdown, non aggiungere titoletti interni o il nome del segno davanti al testo. "
            "Ogni sezione deve avere massimo 2-3 frasi brevi e naturali.\n"
            f"JSON input:\n{json.dumps(compact, ensure_ascii=False)}"
        )
        output = await self._ai.ask_for_task("campaign_editorial", prompt, "Assistente editoriale")
        parsed: dict[str, Any] = {}
        try:
            parsed = json.loads(output or "{}")
            if not isinstance(parsed, dict):
                parsed = {}
        except json.JSONDecodeError:
            parsed = {}
        for sign in SIGN_ORDER:
            sign_payload = signs.get(sign, {})
            rewritten_sign = parsed.get(sign, {}) if isinstance(parsed.get(sign), dict) else {}
            for key in HOROSCOPE_SECTIONS:
                candidate = rewritten_sign.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    sign_payload[key] = sanitize_horoscope_text(sign, candidate)
                else:
                    sign_payload[key] = sanitize_horoscope_text(sign, str(sign_payload.get(key) or ""))
        self._enforce_horoscope_diversity(payload)
        return self._resolve_ai_model_name("campaign_editorial")

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
        output = await self._ai.ask_for_task("campaign_editorial", prompt, "Assistente editoriale")
        return (output or text).strip(), True

    async def load_message_record(self, message_id: str) -> dict[str, Any] | None:
        row = await self._database.get_campaign_content_message(message_id)
        if row is None:
            return None

        payload = dict(row)

        embeds: list[dict[str, Any]] = []
        metadata: dict[str, Any] = {}
        try:
            raw_embeds = json.loads(str(payload.get("embeds_json") or "[]"))
            if isinstance(raw_embeds, list):
                embeds = [item for item in raw_embeds if isinstance(item, dict)]
        except json.JSONDecodeError:
            embeds = []

        try:
            raw_metadata = json.loads(str(payload.get("metadata_json") or "{}"))
            if isinstance(raw_metadata, dict):
                metadata = raw_metadata
        except json.JSONDecodeError:
            metadata = {}

        try:
            current_index = int(payload.get("current_index") or 0)
        except (TypeError, ValueError):
            current_index = 0

        return {
            "message_id": str(payload.get("message_id") or ""),
            "guild_id": str(payload.get("guild_id") or ""),
            "channel_id": str(payload.get("channel_id") or ""),
            "service_type": str(payload.get("service_type") or "").upper(),
            "config_id": str(payload.get("config_id") or ""),
            "embeds": embeds,
            "metadata": metadata,
            "current_index": current_index,
        }

    async def open_personal_navigator(self, interaction: discord.Interaction, *, target_index: int, service_type: str) -> bool:
        message = interaction.message
        if message is None:
            await send_standard_component_notice(interaction, area="campaign navigation", message="Navigazione non disponibile.", kind="warning")
            return False
        record = await self.load_message_record(str(message.id))
        if record is None:
            await send_standard_component_notice(interaction, area="campaign navigation", message="Navigazione non disponibile.", kind="warning")
            return False

        embeds = record.get("embeds", [])
        if not isinstance(embeds, list) or not embeds:
            await send_standard_component_notice(interaction, area="campaign navigation", message="Pagina non disponibile.", kind="warning")
            return False

        metadata = record.get("metadata", {})
        page_map = metadata.get("page_map") if isinstance(metadata, dict) else None
        if not isinstance(page_map, list):
            page_map = self._build_page_map(service_type, payload_embeds=embeds, payload=None)

        index = max(0, min(target_index, len(embeds) - 1))
        view = BaseCampaignNavigatorView(
            self,
            embeds=embeds,
            page_map=page_map,
            service_type=service_type,
            metadata=metadata if isinstance(metadata, dict) else None,
            current_index=index,
            timeout=600,
        )
        embed = self._hydrate_stored_campaign_embed(
            service_type=service_type,
            embed_payload=embeds[index],
            metadata=metadata if isinstance(metadata, dict) else None,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        return True

    async def edit_public_message(self, interaction: discord.Interaction, *, target_index: int) -> bool:
        message = interaction.message
        if message is None:
            return False
        record = await self.load_message_record(str(message.id))
        if record is None:
            return False
        embeds = record.get("embeds", [])
        if not embeds:
            return False
        index = max(0, min(target_index, len(embeds) - 1))
        metadata = record.get("metadata", {})
        page_map = metadata.get("page_map") if isinstance(metadata, dict) else []
        view = PersistentCampaignLauncherView(self, service_type=record.get("service_type") or "NEWS", total_pages=len(embeds), page_map=page_map if isinstance(page_map, list) else [])
        embed = self._hydrate_stored_campaign_embed(
            service_type=str(record.get("service_type") or "NEWS"),
            embed_payload=embeds[index],
            metadata=metadata if isinstance(metadata, dict) else None,
        )
        await interaction.response.edit_message(embed=embed, view=view)
        return True

    def _build_page_map(self, service_type: str, *, payload_embeds: list[Any], payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        if service_type == "NEWS":
            if payload is not None:
                return build_news_page_map(payload)
            categories = list(range(max(0, len(payload_embeds) - 1)))
            return [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}] + [
                {"type": "category", "key": f"cat_{idx+1}", "label": f"📌 CATEGORIA {idx+1}", "page": idx + 1}
                for idx in categories
            ]
        if service_type == "WEATHER":
            return build_weather_page_map()
        if service_type == "HOROSCOPE":
            return build_horoscope_page_map()
        return [{"type": "overview", "key": "overview", "label": "Inizio", "page": 0}]

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

    def _campaign_footer_service_name(self, service_type: str) -> str:
        mapped = {
            "NEWS": "campagne_notizie",
            "WEATHER": "campagne_meteo",
            "HOROSCOPE": "campagne_oroscopo",
        }
        return mapped.get(str(service_type or "").upper(), "campagne_notizie")

    def _campaign_footer_contributors(self, metadata: dict[str, Any] | None) -> list[str]:
        if not isinstance(metadata, dict):
            return []
        contributors: list[str] = []
        seen: set[str] = set()
        for source in metadata.get("used_sources") or metadata.get("configured_sources") or []:
            token = str(source or "").strip()
            if token and token not in seen:
                contributors.append(token)
                seen.add(token)
        model = str(metadata.get("used_model") or metadata.get("ai_model_used") or "").strip()
        if model and model not in {"unknown"} and model not in seen:
            contributors.append(model)
        return contributors

    def _hydrate_stored_campaign_embed(
        self,
        *,
        service_type: str,
        embed_payload: Any,
        metadata: dict[str, Any] | None,
    ) -> discord.Embed:
        embed = discord.Embed.from_dict(embed_payload if isinstance(embed_payload, dict) else {})
        contributors = self._campaign_footer_contributors(metadata)
        attach_footer_meta(
            embed,
            service_name=self._campaign_footer_service_name(service_type),
            contributors=contributors,
            used_local_processing=not contributors,
        )
        return embed

    async def _build_campaign_footer(self, *, service_name: str, used_sources: list[str], used_model: str | None) -> str:
        contributors = list(used_sources)
        model = (used_model or "").strip()
        if model and model not in contributors:
            contributors.append(model)
        text, _ = await self._footer.render_footer(
            service_name=service_name,
            contributors=contributors,
            used_local_processing=not contributors,
        )
        await self._footer.record_service_footer_profile(
            service_name=service_name,
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

    def _resolve_ai_model_name(self, task: str) -> str:
        if self._ai is not None:
            model_cfg = self._ai.get_model_config(task)
            if isinstance(model_cfg, str) and model_cfg.strip():
                return self._ai.get_model_display_name(task)
        return "unknown"
