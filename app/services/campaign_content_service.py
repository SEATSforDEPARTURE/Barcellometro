from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from html import unescape
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import discord

from app.services.ai import AiService
from app.services.campaign_content_fetchers import (
    fetch_daily_news_extras,
    fetch_horoscope_content,
    fetch_news_content,
    fetch_weather_content,
)
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
    _iter_configured_editorial_categories,
    _news_identity,
    _valid_news_items,
    select_final_news_slots,
    sanitize_public_news_text,
    sanitize_horoscope_text,
)
from app.services.database import DatabaseService
from app.services.footer import FooterService, attach_footer_meta
from app.services.footer import attach_footer_meta_to_all
from app.services.discord_embed_utils import hydrate_persisted_embed_with_footer
from app.shared.discord.footer_pipeline import finalize_embeds
from app.services.scheduler_utils import ROME_TZ, calculate_next_wall_clock_run

logger = logging.getLogger(__name__)

_NEWS_INPUT_META_RE = re.compile(
    r"(?im)\b(?:ecco una possibile versione in italiano|versione in italiano|in breve|riassunto|sintesi)\b[:\-\s]*"
)
_NEWS_INPUT_FEED_JUNK_RE = re.compile(r"(?i)\b(?:continua a leggere|leggi anche|clicca qui|read more)\b[^\n.?!]*")
_NEWS_INPUT_SOURCE_TRAIL_RE = re.compile(r"(?i)\bfonte\s*:[^\n]*")
_NEWS_AI_META_RE = re.compile(
    r"(?i)\b(?:ecco|versione in italiano|riassunto|questa notizia|in questa notizia|contenuto fornito)\b"
)
_NEWS_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]",
    flags=re.UNICODE,
)
_NEWS_BOT_OPENING_RE = re.compile(
    r"(?i)^(?:qui la faccenda|qui si parla di|in pratica|attenzione|clima teso|notizia pesante)\b"
)
_NEWS_MAX_BODY_SENTENCES = 1
_NEWS_MAX_BODY_CHARS = 280
_NEWS_EDITORIAL_TAIL_RE = re.compile(
    r"(?i)\b(?:insomma|qui la ruota gira|tema che farà|una vicenda che|notizia durissima|clima resta cupo)\b"
)
_NEWS_DELICATE_KEYWORDS = (
    "morto", "morti", "morte", "vittime", "tragedia", "incidente", "omicidio", "guerra", "bombard", "sparatoria", "alluvione", "terremoto", "aggressione", "violenza",
)
_NEWS_LIGHT_FINAL_EMOJIS = ("👀", "🤹", "📈", "⚡", "🎭")
_NEWS_SERIOUS_FINAL_EMOJIS = ("😔", "🫥")
_COMMON_ENGLISH_NEWS_WORDS = {"the", "and", "with", "breaking", "update", "today", "after", "from", "that", "this"}
_NEWS_EXTRA_ITALIAN_FALLBACKS = {
    "barzelletta": "Il criceto in redazione: «Promesso, oggi apro solo tre tab». Erano trenta.",
    "aforisma": "La notizia corre, il criterio decide la direzione. — Barcellometro",
    "canzone": "Heroes — David Bowie\nEnergia da prima pagina per la ruota della redazione.",
    "meme": "Quando dici «chiudo in 5 minuti» e la breaking spunta al minuto 6.",
}


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
        config = dict(config)
        categories = self._csv_to_list(config.get("categories_json"))
        if not categories:
            categories = self._csv_to_list(config.get("categories"))
        configured_sources = self._normalize_sources(self._json_to_list(config.get("sources_json")))
        payload = fetch_news_content(configured_sources, categories)
        raw_extras = fetch_daily_news_extras(datetime.now(timezone.utc))
        config["extras_payload"] = await self._normalize_news_extras_payload(raw_extras)
        next_run = await self._resolve_next_news_scheduled_run(config)
        if next_run is not None:
            config["next_scheduled_run_at"] = next_run.isoformat()
        used_sources = self._normalize_sources(payload.get("used_sources", []))
        used_model: str | None = None
        fallback_used = False
        if not payload.get("categories"):
            fallback_used = True
            embeds = build_fallback_embed(
                config,
                payload.get("sources", []),
                service_name=self._campaign_footer_service_name("NEWS"),
            )
        else:
            try:
                used_model = await self._rewrite_news_payload(payload)
            except Exception as exc:
                logger.warning("campaign content: news editorial rewrite failed (%s), publishing original payload", exc.__class__.__name__)
                used_model = None
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
        try:
            used_model = await self._rewrite_weather_payload(payload)
        except Exception as exc:
            logger.warning("campaign content: weather editorial rewrite failed (%s), publishing original payload", exc.__class__.__name__)
            used_model = None
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
        try:
            used_model = await self._rewrite_horoscope_payload(payload)
        except Exception as exc:
            logger.warning("campaign content: horoscope editorial rewrite failed (%s), publishing original payload", exc.__class__.__name__)
            used_model = None
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
        config = dict(config)
        now = datetime.now(timezone.utc)
        guild_id = str(config["guild_id"])
        channel_id = str(config["channel_id"])
        footer_sources = used_sources or configured_sources
        footer_service_name = self._campaign_footer_service_name(service_type)
        contributors = [*footer_sources, *([used_model] if used_model else [])]
        attach_footer_meta_to_all(
            embeds,
            service_name=footer_service_name,
            contributors=contributors,
            used_local_processing=not contributors,
        )
        await finalize_embeds(embeds, self._footer, default_service_name=footer_service_name)
        footer_text = getattr(embeds[0].footer, "text", None) or await self._build_campaign_footer(
            service_name=footer_service_name,
            used_sources=footer_sources,
            used_model=used_model,
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
        message = await channel.send(embed=embeds[0])
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
        next_run = calculate_next_wall_clock_run(
            now_utc=now,
            due_slot_iso=str(config.get("next_run_at") or now.isoformat()),
            interval_minutes=interval_minutes,
            jitter_seconds=0,
            tz=ROME_TZ,
        )
        await self._database.update_campaign_content_next_run(guild_id=guild_id, config_id=int(config["id"]), next_run_at=next_run.isoformat(), last_sent_at=now.isoformat())

    async def _rewrite_news_payload(self, payload: dict[str, Any]) -> str | None:
        used_ai = False
        cache: dict[str, str] = {}
        selected_slots = select_final_news_slots(payload)
        payload["selected_news_slots"] = selected_slots
        candidate_count = sum(len(items) for items in payload.get("categories", {}).values() if isinstance(items, list))
        selected_categories = [str(slot.get("category") or "") for slot in selected_slots if isinstance(slot, dict) and slot.get("slot") == "category"]
        logger.info(
            "news_selection_complete candidate_count=%s selected_count=%s category_slots=%s",
            candidate_count,
            len(selected_slots),
            selected_categories,
        )
        selected_category_ids = {
            _news_identity(slot.get("item") or {})
            for slot in selected_slots
            if isinstance(slot, dict) and slot.get("slot") == "category"
        }
        categories = payload.get("categories", {})
        if isinstance(categories, dict):
            used_after_top: set[str] = set()
            for slot in selected_slots:
                if not isinstance(slot, dict):
                    continue
                if slot.get("slot") in {"ultimora", "featured"}:
                    story_id = _news_identity(slot.get("item") or {})
                    if story_id:
                        used_after_top.add(story_id)
            for category in _iter_configured_editorial_categories(payload):
                first_valid = next(iter(_valid_news_items(categories.get(category))), None)
                if not first_valid:
                    continue
                first_id = _news_identity(first_valid)
                if first_id and first_id in used_after_top and first_id not in selected_category_ids:
                    logger.info(
                        "news_slot_skipped reason=already_used slot=%s title=%s",
                        category,
                        str(first_valid.get("title") or "")[:80],
                    )
        logger.info("news_ai_summary_batch_start selected_count=%s", len(selected_slots))
        for slot in selected_slots:
            item = slot.get("item")
            if not isinstance(item, dict):
                continue
            slot_name = str(slot.get("slot") or "unknown")
            if slot_name == "category":
                slot_name = str(slot.get("category") or "category")
            logger.debug("news_ai_summary_start slot=%s title=%s", slot_name, str(item.get("title") or "")[:80])
            ai_summary, ai_used = await self._summarize_news_item_for_embed(item, cache=cache)
            if ai_summary:
                item["ai_summary"] = ai_summary
            item["summary_fallback_used"] = not ai_used
            used_ai = used_ai or ai_used
        return self._resolve_ai_model_name("campaign_editorial") if used_ai else None

    async def _resolve_next_news_scheduled_run(self, config: dict[str, Any]) -> datetime | None:
        guild_id = str(config.get("guild_id") or "").strip()
        channel_id = str(config.get("channel_id") or "").strip()
        service_type = str(config.get("service_type") or "NEWS").upper()
        if not guild_id or not channel_id or service_type != "NEWS":
            return None
        if not hasattr(self._database, "list_campaign_content_recurring_schedule_runs"):
            return None
        rows = await self._database.list_campaign_content_recurring_schedule_runs(
            guild_id=guild_id,
            channel_id=channel_id,
            service_type=service_type,
            after_iso=datetime.now(timezone.utc).isoformat(),
        )
        if not rows:
            return None
        parsed: list[datetime] = []
        for row in rows:
            run_at_raw = str(row.get("next_effective_run_at") or row.get("next_run_at") or "").strip()
            if not run_at_raw:
                continue
            try:
                run_at = datetime.fromisoformat(run_at_raw.replace("Z", "+00:00"))
                parsed.append(run_at if run_at.tzinfo else run_at.replace(tzinfo=timezone.utc))
            except ValueError:
                continue
        if not parsed:
            return None
        return min(parsed)

    async def _summarize_news_item_for_embed(self, item: dict[str, Any], *, cache: dict[str, str]) -> tuple[str, bool]:
        prepared = self._build_news_summary_input(item)
        seed = "|".join(str(prepared.get(k) or "") for k in ("category", "title", "source", "content", "published_at")).strip()
        if seed in cache:
            return cache[seed], True
        title = str(prepared.get("title") or "").strip()
        category = str(prepared.get("category") or "").strip()
        content = str(prepared.get("content") or "").strip()
        source = str(prepared.get("source") or "").strip()
        published_at = str(prepared.get("published_at") or "").strip()
        fallback = self._build_news_summary_fallback(title=title, cleaned_summary=content)
        logger.debug("news_ai_summary_start title=%s category=%s source=%s", title[:80], category or "varie", source or "n/a")
        if self._ai is None or not self._ai.is_enabled():
            logger.info("news_summary_body_generated title=%s chars=%s", title[:80], len(fallback))
            return fallback, False
        prompt = self._build_news_summary_prompt(
            title=title,
            content=content,
            category=category,
            source=source,
            published_at=published_at,
        )
        try:
            output = await self._ai.ask_for_task("campaign_editorial", prompt, "Assistente editoriale")
        except Exception as exc:
            logger.warning("campaign content: news summary ask failed (%s), using fallback summary", exc.__class__.__name__)
            logger.info("news_ai_summary_fallback_used title=%s reason=ai_request_failed", title[:80])
            return fallback, False
        accepted, reason, cleaned = self._is_acceptable_news_ai_summary(
            output or "",
            source_title=title,
            source_summary=content,
        )
        if not accepted:
            logger.info("news_summary_body_rejected reason=%s title=%s", reason, title[:80])
            logger.info("news_ai_summary_fallback_used title=%s", title[:80])
            logger.info("news_summary_body_generated title=%s chars=%s", title[:80], len(fallback))
            return fallback, False
        logger.info("news_ai_summary_accepted title=%s chars=%s", title[:80], len(cleaned))
        logger.info("news_summary_body_generated title=%s chars=%s", title[:80], len(cleaned))
        cache[seed] = cleaned
        return cleaned, True

    @staticmethod
    def _sanitize_news_summary_fallback(text: str) -> str:
        cleaned = CampaignContentService._sanitize_editorial_text(text)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return "Dettagli in aggiornamento."
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", cleaned) if part.strip()]
        if not sentences:
            return cleaned[:220]
        return " ".join(sentences[:_NEWS_MAX_BODY_SENTENCES])[:_NEWS_MAX_BODY_CHARS]

    @staticmethod
    def _news_summary_contains_emoji(text: str) -> bool:
        return bool(_NEWS_EMOJI_RE.search(text or ""))

    @staticmethod
    def _sanitize_news_input_text(text: str) -> str:
        cleaned = unescape(CampaignContentService._sanitize_editorial_text(text))
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"(?im)^\s*-\s*", "", cleaned)
        cleaned = _NEWS_INPUT_META_RE.sub("", cleaned)
        cleaned = _NEWS_INPUT_FEED_JUNK_RE.sub(" ", cleaned)
        cleaned = _NEWS_INPUT_SOURCE_TRAIL_RE.sub(" ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n-•")
        return cleaned

    def _build_news_summary_input(self, item: dict[str, Any]) -> dict[str, str]:
        title = self._sanitize_news_input_text(str(item.get("title") or ""))
        category = self._sanitize_news_input_text(str(item.get("category") or ""))
        source = self._sanitize_news_input_text(str(item.get("source") or ""))
        published_at = self._sanitize_news_input_text(str(item.get("published_at") or ""))
        summary = self._sanitize_news_input_text(str(item.get("summary") or ""))
        description = self._sanitize_news_input_text(str(item.get("description") or ""))
        summary_effective = summary
        if title and summary and SequenceMatcher(None, title.lower(), summary.lower()).ratio() >= 0.9:
            summary_effective = ""
        content = summary_effective or description
        if summary_effective and description and SequenceMatcher(None, summary_effective.lower(), description.lower()).ratio() < 0.8:
            content = f"{summary_effective} {description}".strip()
        if title and content and SequenceMatcher(None, title.lower(), content.lower()).ratio() >= 0.9:
            content = ""
        if not content:
            content = title
        return {
            "title": title,
            "category": category,
            "source": source,
            "published_at": published_at,
            "content": content,
        }

    @staticmethod
    def _build_news_summary_prompt(*, title: str, content: str, category: str, source: str, published_at: str) -> str:
        fields = [f"Titolo: {title or 'n/d'}", f"Contenuto: {content or title or 'n/d'}"]
        if category:
            fields.append(f"Categoria: {category}")
        if source:
            fields.append(f"Fonte tecnica: {source}")
        if published_at:
            fields.append(f"Pubblicata: {published_at}")
        return (
            "Ricevi solo titolo e breve contenuto di una notizia. "
            "Scrivi in italiano un mini-riassunto in una sola frase. "
            "Inizia subito dal contenuto della notizia. "
            "Usa esclusivamente le informazioni fornite: non aggiungere fatti esterni e non inventare dettagli. "
            "Niente introduzioni meta, niente riferimenti al prompt o al tuo ruolo, niente fonte nel testo. "
            "Nessun commento finale del bot. Tono simpatico solo su notizie non tristi; tono sobrio su notizie drammatiche. "
            "Non iniziare con emoji. Usa al massimo una emoji finale coerente col tono, senza altro testo dopo. "
            "Non mettere emoji in mezzo alla frase.\n"
            + "\n".join(fields)
        )

    def _is_acceptable_news_ai_summary(
        self, raw_output: str, *, source_title: str, source_summary: str
    ) -> tuple[bool, str | None, str]:
        cleaned = self._sanitize_news_summary_fallback(self._sanitize_editorial_text(raw_output))
        if not cleaned or len(cleaned) < 24:
            return False, "too_short_or_empty", ""
        if len(cleaned) > 320:
            return False, "too_long", cleaned[:320]
        if _NEWS_AI_META_RE.search(cleaned):
            return False, "meta_output", cleaned
        if re.search(r"<[^>]+>|```", cleaned):
            return False, "dirty_markup", cleaned
        emoji_matches = list(_NEWS_EMOJI_RE.finditer(cleaned))
        if len(emoji_matches) > 1:
            return False, "emoji_multiple", cleaned
        if emoji_matches:
            emoji_match = emoji_matches[0]
            if emoji_match.start() == 0:
                return False, "emoji_at_start", cleaned
            if cleaned[emoji_match.end():].strip():
                return False, "emoji_not_final", cleaned
            if cleaned[:emoji_match.start()].rstrip().endswith((".", "!", "?")):
                return False, "emoji_after_second_sentence", cleaned
        if self._starts_with_bot_comment(cleaned):
            return False, "bot_comment_not_allowed", cleaned
        if _NEWS_EDITORIAL_TAIL_RE.search(cleaned):
            return False, "editorial_tail_not_allowed", cleaned
        sentence_count = len([s for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()])
        if sentence_count > _NEWS_MAX_BODY_SENTENCES:
            return False, "too_many_sentences", cleaned
        source_blob = " ".join(part for part in [source_title, source_summary] if part).strip().lower()
        if source_blob:
            if SequenceMatcher(None, cleaned.lower(), source_blob).ratio() >= 0.9:
                return False, "too_similar_to_source", cleaned
            overlap = SequenceMatcher(None, cleaned.lower(), str(source_summary or "").lower()).ratio()
            if overlap >= 0.87:
                return False, "feed_copy_overlap", cleaned
        english_hits = sum(1 for token in re.findall(r"[a-zA-Z']+", cleaned.lower()) if token in _COMMON_ENGLISH_NEWS_WORDS)
        if english_hits >= 4:
            return False, "unexpected_english", cleaned
        return True, None, cleaned

    @staticmethod
    def _starts_with_emoji(text: str) -> bool:
        first = re.search(r"\S+", text or "")
        if not first:
            return False
        return bool(_NEWS_EMOJI_RE.search(first.group(0)))

    @staticmethod
    def _starts_with_bot_comment(text: str) -> bool:
        return bool(_NEWS_BOT_OPENING_RE.search(sanitize_public_news_text(text).lower().lstrip(" -:;,.!")))

    def _build_news_summary_body(self, text: str) -> str:
        sanitized = sanitize_public_news_text(self._sanitize_news_summary_fallback(text))
        if not sanitized:
            return ""
        sanitized = _NEWS_EMOJI_RE.sub("", sanitized).strip()
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", sanitized) if part.strip()]
        body = " ".join(sentences[:_NEWS_MAX_BODY_SENTENCES]).strip()
        if len(body) > _NEWS_MAX_BODY_CHARS:
            body = body[:_NEWS_MAX_BODY_CHARS].rsplit(" ", 1)[0].strip()
        if body and not re.search(r"[.!?]\s*$", body):
            body = f"{body}."
        return body

    @staticmethod
    def _is_delicate_news(title: str, text: str) -> bool:
        blob = f"{title} {text}".lower()
        return any(token in blob for token in _NEWS_DELICATE_KEYWORDS)

    @staticmethod
    def _pick_news_mood_emoji(*, title: str, text: str) -> str:
        if CampaignContentService._is_delicate_news(title, text):
            palette = _NEWS_SERIOUS_FINAL_EMOJIS
        else:
            palette = _NEWS_LIGHT_FINAL_EMOJIS
        key = f"{title}|{text}".strip().lower() or "news"
        return palette[abs(hash(key)) % len(palette)]

    def _build_news_summary_fallback(self, *, title: str, cleaned_summary: str) -> str:
        base = sanitize_public_news_text(self._sanitize_news_summary_fallback(cleaned_summary))
        if base and title and SequenceMatcher(None, base.lower(), title.lower()).ratio() > 0.9:
            base = ""
        if base:
            if self._starts_with_emoji(base):
                base = re.sub(r"^\s*\S+\s*", "", base).strip()
            if self._starts_with_bot_comment(base):
                base = re.sub(r"(?i)^(?:qui la faccenda|qui si parla di|in pratica|attenzione|clima teso|notizia pesante)\b[^:.\-]*[:.\-]?\s*", "", base).strip()
            body = self._build_news_summary_body(base)
            if body:
                return f"{body} {self._pick_news_mood_emoji(title=title, text=body)}".strip()
        title_clean = self._sanitize_news_input_text(title)
        if not title_clean:
            return "Aggiornamento in corso."
        body = self._build_news_summary_body(f"{title_clean}. Dettagli in aggiornamento.") or "Dettagli in aggiornamento."
        return f"{body} {self._pick_news_mood_emoji(title=title_clean, text=body)}".strip()

    async def _normalize_news_extras_payload(self, payload: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for extra, value in (payload or {}).items():
            normalized[extra] = await self._normalize_single_news_extra(extra, value)
        return normalized

    async def _normalize_single_news_extra(self, extra: str, value: str) -> str:
        cleaned = self._sanitize_news_input_text(value)
        if not cleaned:
            logger.info("news_extra_fallback_used extra=%s reason=empty_content", extra)
            return _NEWS_EXTRA_ITALIAN_FALLBACKS.get(extra, "")
        if self._looks_italian_text(cleaned):
            return cleaned
        if extra == "canzone":
            title_artist = cleaned.split("\n", 1)[0].strip()
            title_artist = title_artist.split(". ", 1)[0].strip() or cleaned
            return f"{title_artist}\nCommento del giorno in italiano dalla regia di Barcellometro."
        translated = ""
        if self._ai is not None and self._ai.is_enabled():
            prompt = (
                f"Adatta in italiano naturale questo contenuto per l'extra '{extra}'. "
                "Mantieni il senso originale, massimo 2 frasi, niente meta-commenti.\n"
                f"Testo: {cleaned}"
            )
            try:
                raw = await self._ai.ask_for_task("campaign_editorial", prompt, "Assistente editoriale")
                translated = self._sanitize_editorial_text(raw or "")
            except Exception as exc:
                logger.debug("news_extra_translation_failed extra=%s error=%s", extra, exc.__class__.__name__)
        if translated and self._looks_italian_text(translated):
            logger.info("news_extra_language_normalized extra=%s source_lang=en target_lang=it", extra)
            return translated
        logger.info("news_extra_fallback_used extra=%s", extra)
        return _NEWS_EXTRA_ITALIAN_FALLBACKS.get(extra, cleaned)

    @staticmethod
    def _looks_italian_text(text: str) -> bool:
        lowered = str(text or "").lower()
        if not lowered:
            return False
        italian_markers = (" che ", " non ", " con ", " per ", " una ", " il ", " la ", " oggi ", " del ")
        english_markers = (" the ", " and ", " with ", " from ", " this ", " that ", " today ", " joke ", " meme ")
        it_score = sum(1 for marker in italian_markers if marker in f" {lowered} ")
        en_score = sum(1 for marker in english_markers if marker in f" {lowered} ")
        return it_score >= max(1, en_score)

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
        output: str | None = None
        try:
            output = await self._ai.ask_for_task("campaign_editorial", prompt, "Assistente editoriale")
        except Exception as exc:
            logger.warning("campaign content: horoscope editorial ask failed (%s), using original payload", exc.__class__.__name__)
        parsed: dict[str, Any] = {}
        ai_applied = False
        try:
            parsed = json.loads(output or "{}")
            if not isinstance(parsed, dict):
                parsed = {}
        except json.JSONDecodeError:
            logger.warning("campaign content: horoscope editorial returned invalid json, using field-level fallbacks")
            parsed = {}
        for sign in SIGN_ORDER:
            sign_payload = signs.get(sign, {})
            rewritten_sign = parsed.get(sign, {}) if isinstance(parsed.get(sign), dict) else {}
            for key in HOROSCOPE_SECTIONS:
                candidate = rewritten_sign.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    sign_payload[key] = sanitize_horoscope_text(sign, candidate)
                    ai_applied = True
                else:
                    sign_payload[key] = sanitize_horoscope_text(sign, str(sign_payload.get(key) or ""))
        self._enforce_horoscope_diversity(payload)
        return self._resolve_ai_model_name("campaign_editorial") if ai_applied else None

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
            "Restituisci solo il testo finale da pubblicare: niente prefazioni, niente etichette tipo 'In breve:', niente meta-commenti, niente spiegazioni del prompt. "
            f"Contesto: {extra_info}.\nTesto:\n{text}"
        )
        try:
            output = await self._ai.ask_for_task("campaign_editorial", prompt, "Assistente editoriale")
        except Exception as exc:
            logger.warning("campaign content: %s editorial rewrite failed (%s), using original text", context, exc.__class__.__name__)
            return text, False
        rewritten = self._sanitize_editorial_text(output or "")
        if not rewritten:
            return text, False
        return rewritten, True

    @staticmethod
    def _sanitize_editorial_text(text: str) -> str:
        cleaned = str(text or "").strip()
        if not cleaned:
            return ""
        cleaned = re.sub(r"```(?:\w+)?", "", cleaned, flags=re.IGNORECASE).replace("```", "")
        cleaned = re.sub(
            r"(?im)^\s*(?:[-•*]\s*)?(?:🧃\s*)?(?:in breve|riassunto|sintesi)\s*:\s*(?:ecco\s+)?(?:la\s+)?(?:riscrizione|versione)\b.*$",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"(?im)^\s*(?:[-•*]\s*)?(?:🧃\s*)?(?:in breve|riassunto|sintesi|testo\s+riformulato)\s*:\s*",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"(?im)^\s*(?:[-•*]\s*)?(?:ecco|ti\s+fornisco|di\s+seguito)\b.{0,120}(?:riscrizione|testo|tono)\b.*$",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"(?im)^\s*(?:nota|istruzione|prompt|output|spiegazione)\s*:\s*.*$",
            "",
            cleaned,
        )
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned

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

    def _build_page_map(self, service_type: str, *, payload_embeds: list[Any], payload: dict[str, Any] | None) -> list[dict[str, Any]]:
        if service_type == "NEWS":
            return build_news_page_map(payload or {})
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

    async def _hydrate_stored_campaign_embed(
        self,
        *,
        service_type: str,
        embed_payload: Any,
        metadata: dict[str, Any] | None,
    ) -> discord.Embed:
        embed = discord.Embed.from_dict(embed_payload if isinstance(embed_payload, dict) else {})
        contributors = self._campaign_footer_contributors(metadata)
        await hydrate_persisted_embed_with_footer(
            embed,
            footer_context={
                "service_name": self._campaign_footer_service_name(service_type),
                "contributors": contributors,
                "used_local_processing": not contributors,
            },
            default_service_name=self._campaign_footer_service_name(service_type),
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
        def _compact_source(source: str) -> str:
            token = str(source or "").strip()
            if not token:
                return ""
            parsed = urlparse(token)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                host = parsed.netloc.lower()
                if host.startswith("www."):
                    host = host[4:]
                return host
            return token.lower()

        normalized: list[str] = []
        seen: set[str] = set()
        for source in sources:
            token = _compact_source(source)
            if not token or token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized

    def _resolve_ai_model_name(self, task: str) -> str:
        if self._ai is not None:
            model_cfg = self._ai.get_model_config(task)
            if isinstance(model_cfg, str) and model_cfg.strip():
                get_display_name = getattr(self._ai, "get_model_display_name", None)
                if callable(get_display_name):
                    return str(get_display_name(task))
                return model_cfg
        return "unknown"
