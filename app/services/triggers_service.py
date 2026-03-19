from __future__ import annotations

import asyncio
import difflib
import json
import logging
import hashlib
import os
import random
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, Literal

import discord

from app.core.config_paths import BARCELLO_TRIGGER_JSON
from app.services.footer import FooterService, attach_footer_meta
from app.shared.discord.command_embeds import send_standard_response
from app.shared.discord.report_embeds import build_report_cover_embed

from app.services.barcello_service import BarcelloService
from app.services.barcello_window_defaults import resolve_window_minutes
from app.services.community_insights import CommunityInsightsService
from app.config.file_loader import load_json_file
from app.services.database import DatabaseService
from app.services.entitlements import EntitlementsService
from app.services.ingest import EventEnvelope
from app.services.qna_session_store import QnaSession, QnaSessionStore
from app.services.qna_sessions_repo import QnaSessionsRepo
from app.services.qna_query_engine import QnaAnswerResult, QnaQueryEngine
from app.shared.safety.pii import contains_pii

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")
PHRASE_FALLBACK_TEMPLATES = {
    "DEFAULT": "È la {count_user}ª volta che lo dici. L'ultima è stata {last_seen_human} fa. 👀",
    "FIRST": "È la prima volta che lo dici. 👀",
}
PHRASE_PLACEHOLDERS = {
    "{author}",
    "{author_name}",
    "{phrase}",
    "{count_user_prev}",
    "{count_user}",
    "{last_seen_human}",
    "{last_seen_dt}",
    "{custom_user_phrase}",
    "{milestone}",
    "{next_milestone}",
    "{remaining_to_next_milestone}",
}
IT_STOPWORDS = {
    "a", "ad", "ai", "al", "all", "alla", "alle", "anche", "avete", "che", "chi", "ci", "coi", "col", "come",
    "con", "cosa", "da", "dagli", "dai", "dal", "dalla", "dalle", "dei", "degli", "del", "della", "delle", "dello",
    "di", "dove", "e", "ed", "era", "erano", "essere", "fatto", "ha", "hai", "hanno", "ho", "i", "il", "in", "io",
    "la", "le", "li", "lo", "loro", "ma", "mi", "nei", "nel", "nella", "no", "non", "o", "per", "perche", "perché",
    "piu", "più", "poi", "puo", "può", "quale", "quali", "quello", "questa", "questo", "se", "sei", "si", "solo", "sono",
    "su", "sul", "sulla", "tra", "tu", "un", "una", "uno", "vi", "voi",
}


class TriggerEngineService:
    def __init__(
        self,
        database: DatabaseService,
        barcello: BarcelloService,
        entitlements: EntitlementsService,
        ai_service,
        community_insights: CommunityInsightsService | None = None,
    ) -> None:
        self._database = database
        self._barcello = barcello
        self._entitlements = entitlements
        self._ai = ai_service
        self._community_insights = community_insights or CommunityInsightsService(ai_service)
        self._footer = FooterService(database)
        self._bot: discord.Client | None = None
        self._task: asyncio.Task[None] | None = None
        self._recovery_task: asyncio.Task[None] | None = None
        self._barcello_eval_tasks: dict[str, asyncio.Task[None]] = {}
        self._barcello_moods_missing_warned = False
        self._barcello_trigger_cfg: dict[str, Any] | None = None
        self._barcello_trigger_cfg_mtime: float | None = None
        self._barcello_trigger_cfg_path = BARCELLO_TRIGGER_JSON
        self._barcello_trigger_cfg_missing_warned = False
        self._barcello_window_override_cache: dict[str, int] = {}
        self._barcello_window_override_cache_fingerprint: str | None = None
        self._barcello_last_applied_window: dict[str, int] = {}
        self._qna_sessions = QnaSessionStore(ttl_minutes=60)
        self._qna_sessions_repo = QnaSessionsRepo(database)
        self._qna_query_engine = QnaQueryEngine(database=database, ai_service=ai_service, barcello=barcello)

    def start(self, bot: discord.Client) -> None:
        self._bot = bot
        if self._task is None:
            self._task = asyncio.create_task(self._insights_loop())
        if self._recovery_task is None:
            self._recovery_task = asyncio.create_task(self._barcello_recovery_loop())
        asyncio.create_task(self._qna_sessions_repo.delete_expired_sessions())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            self._recovery_task = None
        for task in self._barcello_eval_tasks.values():
            task.cancel()
        self._barcello_eval_tasks.clear()

    async def on_event(self, envelope: EventEnvelope) -> None:
        if envelope.event_type != "message.create":
            return
        if not envelope.guild_id or not envelope.channel_id or not envelope.content:
            return
        await self._handle_phrases(envelope)
        await self._on_barcello_message(envelope)

    async def _qna_reply(
        self,
        interaction: discord.Interaction,
        text: str,
        *,
        ephemeral: bool,
        kind: Literal["info", "success", "warning", "error"] = "warning",
    ) -> None:
        await send_standard_response(
            interaction,
            top_level="domanda",
            subcommand_path="domanda",
            lines=[("dettaglio", text)],
            kind=kind,
            footer_service=self._footer,
            ephemeral=ephemeral,
        )

    async def _send_qna_error(
        self,
        interaction: discord.Interaction,
        *,
        question: str,
        asker_name: str,
        message: str = "Non riesco a rispondere qui in questo momento.",
        ephemeral: bool = False,
    ) -> None:
        _ = question
        _ = asker_name
        await send_standard_response(
            interaction,
            top_level="domanda",
            subcommand_path="domanda",
            lines=[("errore", message)],
            kind="error",
            footer_service=self._footer,
            ephemeral=ephemeral,
        )


    def _trim_qna_history(self, history: list[dict[str, str]], *, max_messages: int = 16) -> list[dict[str, str]]:
        if max_messages <= 0:
            return []
        trimmed = history[-max_messages:]
        while trimmed and str(trimmed[0].get("role") or "") == "assistant":
            trimmed = trimmed[1:]
        return trimmed

    async def handle_qna_question(
        self,
        interaction: discord.Interaction,
        question: str,
        *,
        scope_override: Literal["channel", "global"] | None = None,
    ) -> None:
        mapped_scope: Literal["channel_qna", "general_llm"] | None = None
        if scope_override == "global":
            mapped_scope = "general_llm"
        elif scope_override == "channel":
            mapped_scope = "channel_qna"
        await self.route_qna(interaction, question, scope=mapped_scope)

    async def route_qna(
        self,
        interaction: discord.Interaction,
        question: str,
        *,
        scope: Literal["channel_qna", "general_llm"] | None = None,
    ) -> None:
        question_text = (question or "").strip()
        if interaction.guild_id is None or interaction.channel_id is None:
            await self._qna_reply(interaction, "Usa questo comando in un canale.", ephemeral=True, kind="error")
            return
        if not question_text:
            await self._qna_reply(interaction, "Inserisci una domanda valida.", ephemeral=True, kind="error")
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False, thinking=True)

        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        user_id = str(interaction.user.id)
        route_scope = scope or "channel_qna"
        logger.info("qna_dispatch scope=%s guild=%s channel=%s user=%s", route_scope, guild_id, channel_id, user_id)

        if route_scope == "channel_qna" and not await self._database.get_trigger_enabled(guild_id, channel_id, "qna"):
            await self._qna_reply(interaction, "Il trigger Q&A non è abilitato in questo canale.", ephemeral=True, kind="warning")
            return
        if route_scope == "channel_qna" and is_out_of_scope_question(question_text):
            await self._qna_reply(interaction, "Posso rispondere solo su questo canale.", ephemeral=True, kind="warning")
            return
        if is_sensitive_question(question_text):
            await self._qna_reply(interaction, "Non posso aiutare con dati personali o sensibili.", ephemeral=True, kind="error")
            return

        profile = await self._entitlements.resolve_profile(interaction.user)
        limits = await self._get_qna_daily_limits()
        limit_plus = int(limits.get("role1", 1))
        limit_pro = int(limits.get("role2", 2))
        limit_promax = int(limits.get("role3", 3))
        if profile == "base":
            upgrade_text = (
                "Per fare domande devi fare l'upgrade a PLUS, PRO o PRO MAX.\n"
                f"• PLUS: {limit_plus} domande/giorno\n"
                f"• PRO: {limit_pro} domande/giorno\n"
                f"• PRO MAX: {limit_promax} domande/giorno"
            )
            await self._qna_reply(interaction, upgrade_text, ephemeral=True, kind="info")
            return

        limit = await self._resolve_qna_limit(interaction, profile=profile, limits=limits)
        window_date = datetime.now(ROME_TZ).date().isoformat()
        used = await self._database.get_usage(guild_id, user_id, "qna", window_date)
        if used >= limit:
            if profile == "role1":
                delta = max(0, limit_pro - limit_plus)
                message = f"Domande terminate, aggiorna al piano PRO per avere +{delta} al giorno."
            elif profile == "role2":
                delta = max(0, limit_promax - limit_pro)
                message = f"Domande terminate, aggiorna al piano PRO MAX per avere +{delta} al giorno."
            elif profile == "role3":
                message = "Domande terminate, aspetta domani per averne altre."
            else:
                message = "Hai esaurito le domande di oggi."
            await self._qna_reply(interaction, message, ephemeral=True, kind="warning")
            return

        question_clean = question_text
        if not question_clean.endswith("?"):
            question_clean = f"{question_clean}?"
        asker_name = getattr(interaction.user, "display_name", None) or getattr(interaction.user, "name", None) or "Utente"

        if route_scope == "general_llm":
            history = [{"role": "user", "content": question_clean}]
            text = await self._ask_general_answer(question_clean, history=history)
            if not text:
                await self._send_qna_error(interaction, question=question_clean, asker_name=asker_name)
                return
            history.append({"role": "assistant", "content": text})
            history = self._trim_qna_history(history)
            evidence_pack: list[dict[str, str]] = []
            response_origin: Literal["remote_ai", "local_backend", "error"] = "remote_ai"
            model_name: str | None = self._get_qna_remote_model_name()
        else:
            answer = await self._handle_qna(
                scope="channel",
                guild_id=guild_id,
                channel_id=channel_id,
                question=question_clean,
                source=interaction,
            )
            if answer is None:
                await self._send_qna_error(interaction, question=question_clean, asker_name=asker_name)
                return
            if not answer.get("can_answer"):
                await self._send_qna_error(interaction, question=question_clean, asker_name=asker_name)
                return
            text = str(answer.get("answer") or "").strip()
            if not text:
                await self._send_qna_error(interaction, question=question_clean, asker_name=asker_name)
                return

            evidence_pack = answer.get("evidence_pack") if isinstance(answer, dict) else []
            if not isinstance(evidence_pack, list):
                evidence_pack = []
            answer_mode = str(answer.get("answer_mode") or "") if isinstance(answer, dict) else ""
            response_origin = "local_backend"
            model_name = None

        if contains_pii(text):
            await self._qna_reply(interaction, "Non posso condividere dati personali.", ephemeral=True, kind="error")
            return

        answer_mode = str(answer.get("answer_mode") or "") if route_scope != "general_llm" and isinstance(answer, dict) else ""
        render_mode: Literal["evidence", "plain"] = "plain" if route_scope == "general_llm" or answer_mode == "semantic_plain" else "evidence"
        render_evidence = evidence_pack if render_mode == "evidence" else []
        logger.info("qna_render mode=%s scope=%s evidence_items=%d", render_mode, route_scope, len(render_evidence))
        formatted_answer = self._format_qna_answer_text(question_clean, text, render_evidence, scope=route_scope, mode=render_mode)
        if route_scope == "channel_qna" and answer_mode == "semantic_plain":
            formatted_answer = self._append_qna_proofs_section(formatted_answer, evidence_pack)
        embed = self._build_qna_embed(
            asker_name,
            question_clean,
            formatted_answer,
            response_origin=response_origin,
            model_name=model_name,
        )

        await self._database.increment_usage(
            guild_id,
            user_id,
            "qna",
            window_date,
            datetime.now(timezone.utc).isoformat(),
        )
        sent_message = await interaction.followup.send(embed=embed, ephemeral=False, wait=True)
        if route_scope == "general_llm":
            message_id_raw = getattr(sent_message, "id", None)
            if message_id_raw is not None:
                try:
                    anchor_key = (int(guild_id), int(channel_id), int(message_id_raw))
                except (TypeError, ValueError):
                    anchor_key = None
                if anchor_key is not None:
                    session = QnaSession(scope="general_llm", history=history)
                    self._qna_sessions.set(anchor_key, session)
                    await self._qna_sessions_repo.save_session(
                        anchor_message_id=anchor_key[2],
                        guild_id=anchor_key[0],
                        channel_id=anchor_key[1],
                        user_id=int(user_id),
                        scope=session.scope,
                        history=session.history,
                        model_name=self._get_qna_remote_model_name(),
                        created_at=session.created_at,
                    )

    async def _send_qna_session_unavailable(self, message: discord.Message) -> None:
        text = "Questa conversazione non è più disponibile. Usa `/domanda` per iniziare una nuova sessione."
        try:
            await message.author.send(text)
        except Exception:
            logger.info("qna_session_unavailable_dm_failed user_id=%s", getattr(message.author, "id", None))

    async def _resolve_reference_message(self, message: discord.Message) -> discord.Message | None:
        if not message.reference or not message.reference.message_id:
            return None
        resolved = getattr(message.reference, "resolved", None)
        if isinstance(resolved, discord.Message):
            return resolved
        try:
            return await message.channel.fetch_message(message.reference.message_id)
        except Exception:
            return None

    def _is_qna_bot_embed_message(self, message: discord.Message | None) -> bool:
        if message is None:
            return False
        if self._bot is not None and getattr(message.author, "id", None) != getattr(self._bot.user, "id", None):
            return False
        embeds = getattr(message, "embeds", None) or []
        if not embeds:
            return False
        title = str(getattr(embeds[0], "title", "") or "").replace(" ", "")
        return title == "❓BOTTA&RISPOSTA"

    async def handle_message_qna(self, message: discord.Message) -> None:
        try:
            if message.guild is None:
                return
            content = (message.content or "").strip()
            if not content:
                return

            if message.reference and message.reference.message_id and message.channel and message.guild:
                anchor_key = (int(message.guild.id), int(message.channel.id), int(message.reference.message_id))
                session = self._qna_sessions.get(anchor_key)
                if session is None:
                    persisted = await self._qna_sessions_repo.get_session(anchor_key[2])
                    if persisted and persisted.guild_id == anchor_key[0] and persisted.channel_id == anchor_key[1]:
                        session = persisted.session
                        self._qna_sessions.set(anchor_key, session)
                if session and session.scope == "general_llm":
                    question_clean = content if content.endswith("?") else f"{content}?"
                    session.history.append({"role": "user", "content": question_clean})
                    session.history = self._trim_qna_history(session.history)
                    answer_text = await self._ask_general_answer(question_clean, history=session.history)
                    if answer_text:
                        session.history.append({"role": "assistant", "content": answer_text})
                        session.history = self._trim_qna_history(session.history)
                        formatted_answer = self._format_qna_answer_text(
                            question_clean,
                            answer_text,
                            [],
                            scope="general_llm",
                            mode="plain",
                        )
                        reply_embed = self._build_qna_embed(
                            getattr(message.author, "display_name", None) or getattr(message.author, "name", None) or "Utente",
                            question_clean,
                            formatted_answer,
                            response_origin="remote_ai",
                            model_name=self._get_qna_remote_model_name(),
                            is_followup=True,
                        )
                        reply_message = await message.reply(embed=reply_embed, mention_author=False)
                        base_key = (int(message.guild.id), int(message.channel.id), int(message.reference.message_id))
                        new_anchor_key = (int(message.guild.id), int(message.channel.id), int(reply_message.id))
                        self._qna_sessions.set(base_key, session)
                        self._qna_sessions.set(new_anchor_key, session)
                        await self._qna_sessions_repo.save_session(
                            anchor_message_id=base_key[2],
                            guild_id=base_key[0],
                            channel_id=base_key[1],
                            user_id=int(message.author.id),
                            scope=session.scope,
                            history=session.history,
                            model_name=self._get_qna_remote_model_name(),
                            created_at=session.created_at,
                        )
                        await self._qna_sessions_repo.save_session(
                            anchor_message_id=new_anchor_key[2],
                            guild_id=new_anchor_key[0],
                            channel_id=new_anchor_key[1],
                            user_id=int(message.author.id),
                            scope=session.scope,
                            history=session.history,
                            model_name=self._get_qna_remote_model_name(),
                            created_at=session.created_at,
                        )
                        logger.info("qna_session_hit=true scope=general_llm history_len=%s", len(session.history))
                    else:
                        error_embed = self._build_qna_embed(
                            getattr(message.author, "display_name", None) or getattr(message.author, "name", None) or "Utente",
                            question_clean,
                            "Non riesco a rispondere qui in questo momento.",
                            response_origin="error",
                            is_followup=True,
                        )
                        await message.reply(embed=error_embed, mention_author=False)
                    return
                referenced_message = await self._resolve_reference_message(message)
                if self._is_qna_bot_embed_message(referenced_message):
                    await self._send_qna_session_unavailable(message)
                    return

            question = content
            if question.lower().startswith("domanda:"):
                question = question.split(":", 1)[1].strip()
            if not question:
                return
            if "?" not in question and not content.lower().startswith("domanda:"):
                return

            guild_id = str(message.guild.id)
            channel_id = str(message.channel.id)
            if not await self._database.get_trigger_enabled(guild_id, channel_id, "qna"):
                return
            if is_out_of_scope_question(question):
                await message.reply("Posso rispondere solo su questo canale.", mention_author=False)
                return
            if is_sensitive_question(question):
                await message.reply("Non posso aiutare con dati personali o sensibili.", mention_author=False)
                return

            profile = await self._entitlements.resolve_profile(message.author)
            limits = await self._get_qna_daily_limits()
            limit_plus = int(limits.get("role1", 1))
            limit_pro = int(limits.get("role2", 2))
            limit_promax = int(limits.get("role3", 3))
            if profile == "base":
                await message.reply("Per fare domande usa /domanda e fai upgrade a PLUS/PRO/PRO MAX.", mention_author=False)
                return

            limit = await self._resolve_qna_limit_for_member(message.author, profile=profile, limits=limits)
            window_date = datetime.now(ROME_TZ).date().isoformat()
            used = await self._database.get_usage(guild_id, str(message.author.id), "qna", window_date)
            if used >= limit:
                if profile == "role1":
                    delta = max(0, limit_pro - limit_plus)
                    quota_msg = f"Domande terminate, aggiorna al piano PRO per avere +{delta} al giorno."
                elif profile == "role2":
                    delta = max(0, limit_promax - limit_pro)
                    quota_msg = f"Domande terminate, aggiorna al piano PRO MAX per avere +{delta} al giorno."
                elif profile == "role3":
                    quota_msg = "Domande terminate, aspetta domani per averne altre."
                else:
                    quota_msg = "Hai esaurito le domande di oggi."
                await message.reply(quota_msg, mention_author=False)
                return

            question_clean = question.strip()
            if not question_clean.endswith("?"):
                question_clean = f"{question_clean}?"

            scope = await self._decide_qna_scope(question_clean)
            logger.info(
                "qna scope=%s guild_id=%s channel_id=%s user_id=%s len(question)=%s",
                scope,
                guild_id,
                channel_id,
                str(message.author.id),
                len(question_clean),
            )
            answer = await self._handle_qna(
                scope=scope,
                guild_id=guild_id,
                channel_id=channel_id,
                question=question_clean,
                source=message,
            )
            if answer is None or not answer.get("can_answer"):
                error_embed = self._build_qna_embed(
                    getattr(message.author, "display_name", None) or getattr(message.author, "name", None) or "Utente",
                    question_clean,
                    "Non riesco a rispondere qui in questo momento.",
                    response_origin="error",
                )
                await message.reply(embed=error_embed, mention_author=False)
                return

            text = str(answer.get("answer") or "").strip()
            if not text:
                error_embed = self._build_qna_embed(
                    getattr(message.author, "display_name", None) or getattr(message.author, "name", None) or "Utente",
                    question_clean,
                    "Non riesco a rispondere qui in questo momento.",
                    response_origin="error",
                )
                await message.reply(embed=error_embed, mention_author=False)
                return

            evidence_pack = answer.get("evidence_pack") if isinstance(answer, dict) else []
            if not isinstance(evidence_pack, list):
                evidence_pack = []
            answer_mode = str(answer.get("answer_mode") or "") if isinstance(answer, dict) else ""

            if contains_pii(text):
                await message.reply("Non posso condividere dati personali.", mention_author=False)
                return

            await self._database.increment_usage(guild_id, str(message.author.id), "qna", window_date, datetime.now(timezone.utc).isoformat())
            render_mode: Literal["evidence", "plain"] = "plain" if answer_mode == "semantic_plain" else "evidence"
            render_evidence = evidence_pack if render_mode == "evidence" else []
            formatted_answer = self._format_qna_answer_text(
                question_clean,
                text,
                render_evidence,
                scope="channel_qna",
                mode=render_mode,
            )
            if answer_mode == "semantic_plain":
                formatted_answer = self._append_qna_proofs_section(formatted_answer, evidence_pack)
            embed = self._build_qna_embed(
                getattr(message.author, "display_name", None) or getattr(message.author, "name", None) or "Utente",
                question_clean,
                formatted_answer,
                response_origin="local_backend",
            )
            await message.reply(embed=embed, mention_author=False)
        except Exception:  # noqa: BLE001
            logger.exception(
                "handle_message_qna failed",
                extra={
                    "guild_id": str(message.guild.id) if message.guild else "",
                    "channel_id": str(getattr(message.channel, "id", "") or ""),
                    "message_id": str(getattr(message, "id", "") or ""),
                },
            )
            return

    async def configure_insights(self, prompt_text: str) -> dict[str, object]:
        config = await self._community_insights.parse_config_prompt(prompt_text)
        await self._database.set_setting("community_insights.config", json.dumps(config, ensure_ascii=False))
        return config

    async def get_insights_status(self, guild_id: str, channel_id: str) -> dict[str, object]:
        raw = await self._database.get_setting("community_insights.config")
        config = await self._community_insights.get_config(raw)
        enabled = await self._database.get_trigger_enabled(guild_id, channel_id, "insights")
        state = await self._database.get_trigger_state(guild_id, channel_id, "insights")
        return self._community_insights.status(enabled, config, state.get("last_post_at"))

    async def get_qna_quota_for_member(self, member, guild_id: str, channel_id: str | None = None) -> dict[str, object]:
        _ = channel_id
        profile = await self._entitlements.resolve_profile(member)
        limit = await self._resolve_qna_limit_for_member(member)
        window_date = datetime.now(ROME_TZ).date().isoformat()
        used = await self._database.get_usage(guild_id, str(member.id), "qna", window_date)
        now_rome = datetime.now(ROME_TZ)
        reset_local = datetime.combine(now_rome.date() + timedelta(days=1), datetime.min.time(), tzinfo=ROME_TZ)
        remaining = max(0, limit - used)
        return {
            "tier": profile,
            "limit": limit,
            "used": used,
            "remaining": remaining,
            "resets_at_iso": reset_local.isoformat(),
        }

    async def _insights_loop(self) -> None:
        while True:
            try:
                await self._poll_insights()
            except Exception:  # noqa: BLE001
                logger.exception("Trigger insights poll failed")
            await asyncio.sleep(60)


    async def _maybe_set_daily_random_mood(
        self,
        guild_id: str,
        channel_id: str,
        cfg: dict[str, object],
        now_rome: datetime,
    ) -> None:
        daily_random_enabled = bool(cfg.get("mood_daily_random", False))
        if not daily_random_enabled:
            return

        channels_filter = cfg.get("mood_daily_random_channels")
        if isinstance(channels_filter, list) and channels_filter:
            allowed_channels = {str(item) for item in channels_filter if str(item).strip()}
            if channel_id not in allowed_channels:
                return

        trigger_time_raw = cfg.get("mood_daily_random_time_local")
        trigger_time_text = str(trigger_time_raw or "06:00")
        try:
            hour_text, minute_text = trigger_time_text.split(":", 1)
            trigger_hour = int(hour_text)
            trigger_minute = int(minute_text)
            if not (0 <= trigger_hour <= 23 and 0 <= trigger_minute <= 59):
                raise ValueError
        except ValueError:
            trigger_hour = 6
            trigger_minute = 0

        if (now_rome.hour, now_rome.minute) < (trigger_hour, trigger_minute):
            return

        moods_cfg = cfg.get("moods")
        if not isinstance(moods_cfg, dict) or not moods_cfg:
            if not self._barcello_moods_missing_warned:
                logger.warning("Daily random mood enabled but cfg.moods is missing/empty; skipping")
                self._barcello_moods_missing_warned = True
            return

        today = now_rome.date().isoformat()
        state = await self._database.get_trigger_state(guild_id, channel_id, "barcello_mood")
        if str(state.get("date") or "") == today:
            return

        mood_names = sorted(str(name) for name in moods_cfg.keys())
        if not mood_names:
            return

        avoid_repeat = bool(cfg.get("mood_daily_random_avoid_repeat", True))
        yesterday = (now_rome.date() - timedelta(days=1)).isoformat()
        yesterday_mood = str(state.get("mood") or "") if str(state.get("date") or "") == yesterday else ""

        candidates = mood_names
        if avoid_repeat and yesterday_mood and len(mood_names) >= 2:
            filtered = [name for name in mood_names if name != yesterday_mood]
            if filtered:
                candidates = filtered

        seed = f"{today}:{guild_id}:{channel_id}"
        chosen = random.Random(seed).choice(candidates)
        await self._database.set_trigger_state(
            guild_id,
            channel_id,
            "barcello_mood",
            {"mood": chosen, "date": today, "mode": "daily_random"},
        )
        logger.info("Daily random mood set guild_id=%s channel_id=%s chosen=%s", guild_id, channel_id, chosen)

    async def _poll_barcello(self) -> None:
        """Legacy/manual wrapper: evaluates enabled channels once without aggressive scheduling."""
        rows = await self._database.list_enabled_trigger_channels("barcello")
        for row in rows:
            await self._evaluate_barcello_channel(str(row["guild_id"]), str(row["channel_id"]), reason="legacy_poll")

    async def _on_barcello_message(self, envelope: EventEnvelope) -> None:
        if envelope.event_type != "message.create" or not envelope.guild_id or not envelope.channel_id:
            return
        if not await self._database.get_trigger_enabled(envelope.guild_id, envelope.channel_id, "barcello"):
            return
        await self._schedule_barcello_eval(envelope.guild_id, envelope.channel_id)

    async def _schedule_barcello_eval(self, guild_id: str, channel_id: str) -> None:
        key = f"{guild_id}:{channel_id}"
        existing = self._barcello_eval_tasks.get(key)
        if existing and not existing.done():
            logger.debug("barcello debounce skipped task already pending key=%s", key)
            return
        task = asyncio.create_task(self._debounced_barcello_eval(guild_id, channel_id))
        self._barcello_eval_tasks[key] = task
        logger.debug("barcello debounce scheduled key=%s", key)

    async def _debounced_barcello_eval(self, guild_id: str, channel_id: str) -> None:
        key = f"{guild_id}:{channel_id}"
        config = self._load_barcello_trigger_cfg_cached()
        event_cfg = config.get("event_driven") if isinstance(config.get("event_driven"), dict) else {}
        debounce_seconds = int(event_cfg.get("debounce_seconds") or 30)
        try:
            await asyncio.sleep(max(1, debounce_seconds))
            logger.debug("barcello event eval start key=%s", key)
            await self._evaluate_barcello_channel(guild_id, channel_id, reason="event")
            logger.debug("barcello event eval end key=%s", key)
        finally:
            self._barcello_eval_tasks.pop(key, None)

    async def _evaluate_barcello_channel(
        self,
        guild_id: str,
        channel_id: str,
        *,
        reason: str = "event",
        allow_recovery: bool = False,
    ) -> None:
        if self._bot is None:
            return
        config = self._load_barcello_trigger_cfg_cached()
        window_minutes_global = config.get("window_minutes")
        if not isinstance(window_minutes_global, int) or window_minutes_global <= 0:
            window_minutes_global = 60
        min_messages = config.get("min_messages")
        if not isinstance(min_messages, int) or min_messages <= 0:
            min_messages = 10
        min_score_delta_for_notify = config.get("min_score_delta_for_notify")
        if not isinstance(min_score_delta_for_notify, int) or min_score_delta_for_notify < 0:
            min_score_delta_for_notify = 3
        now_rome = datetime.now(ROME_TZ)
        await self._maybe_set_daily_random_mood(guild_id, channel_id, config, now_rome)
        window_minutes_effective = self._get_effective_window_minutes(
            cfg=config,
            channel_id=channel_id,
            default_window=window_minutes_global,
        )
        if window_minutes_effective != window_minutes_global:
            previous_window = self._barcello_last_applied_window.get(channel_id)
            if previous_window != window_minutes_effective:
                self._barcello_last_applied_window[channel_id] = window_minutes_effective
                logger.info(
                    "barcello window override applied channel_id=%s window=%s (prev=%s)",
                    channel_id,
                    window_minutes_effective,
                    previous_window,
                )
        window_end = datetime.now(timezone.utc)
        window_start = window_end - timedelta(minutes=window_minutes_effective)
        count_row = await self._database.fetchone(
                """
                SELECT COUNT(*) AS count
                FROM messages AS m
                LEFT JOIN users AS u ON u.user_id = m.author_id
                WHERE m.channel_id = ?
                  AND m.ts >= ?
                  AND m.ts <= ?
                  AND COALESCE(m.is_deleted, 0) = 0
                  AND COALESCE(u.is_bot, 0) = 0
                """,
                (channel_id, window_start.isoformat(), window_end.isoformat()),
            )
        message_count = int(count_row["count"]) if count_row else 0
        if message_count < min_messages and not allow_recovery:
            logger.debug(
                "barcello skip low activity channel=%s count=%s min_messages=%s reason=%s",
                channel_id,
                message_count,
                min_messages,
                reason,
            )
            return
        status = await self._barcello.get_current_status(
                guild_id,
                channel_id=channel_id,
                window_minutes=window_minutes_effective,
            )
        raw_color = self._normalize_barcello_color(status.get("color"))
        if raw_color is None:
            return
        score = int(status.get("score") or 0)
        prev = await self._database.get_barcello_trigger_state(guild_id, channel_id)
        prev_color = self._normalize_barcello_color(prev.get("last_color") if prev else None)
        prev_score = int(prev.get("last_score")) if prev and prev.get("last_score") is not None else None
        stable_color = self._apply_hysteresis(prev_color, raw_color, score)
        stored_color = stable_color or ""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        recovery_armed = bool((prev or {}).get("recovery_armed"))
        recovery_from = self._normalize_barcello_color((prev or {}).get("recovery_from"))
        candidate_color = self._normalize_barcello_color((prev or {}).get("candidate_color"))
        candidate_since_ts = str((prev or {}).get("candidate_since_ts") or "")

        confirm_seconds = int(((config.get("event_driven") or {}).get("minor_state_confirm_seconds") or 180))
        is_minor_flip = prev_color in {"VERDE", "GIALLO"} and stored_color in {"VERDE", "GIALLO"} and prev_color != stored_color
        if is_minor_flip:
            if candidate_color != stored_color:
                await self._database.update_barcello_candidate_state(
                    guild_id,
                    channel_id,
                    candidate_color=stored_color,
                    candidate_since_ts=now_iso,
                )
                await self._database.upsert_barcello_trigger_state(guild_id, channel_id, prev_color, score, now_iso)
                logger.debug("barcello minor transition pending confirm channel=%s transition=%s->%s", channel_id, prev_color, stored_color)
                return
            try:
                candidate_since = datetime.fromisoformat(candidate_since_ts) if candidate_since_ts else now
            except ValueError:
                candidate_since = now
            if candidate_since.tzinfo is None:
                candidate_since = candidate_since.replace(tzinfo=timezone.utc)
            if (now - candidate_since).total_seconds() < confirm_seconds:
                logger.debug("barcello minor transition suppressed by confirmation channel=%s transition=%s->%s", channel_id, prev_color, stored_color)
                return
        else:
            await self._database.update_barcello_candidate_state(guild_id, channel_id, candidate_color=None, candidate_since_ts=None)

        should_notify = prev_color is None
        is_recovery_notify = False
        transition = f"{prev_color}->{stored_color}" if prev_color else f"INIT->{stored_color}"

        if prev_color is not None and stored_color == prev_color:
            should_notify = False
        elif prev_color == "GIALLO" and stored_color == "VERDE":
            if not recovery_armed:
                should_notify = False
                logger.info("barcello giallo->verde suppressed because not recovery channel=%s", channel_id)
            else:
                if not allow_recovery:
                    should_notify = False
                else:
                    quiet_minutes = int(((config.get("recovery") or {}).get("min_quiet_minutes") or 12))
                    last_red = await self._database.get_barcello_last_seen_for_color(guild_id, channel_id, recovery_from or "ROSSO")
                    enough_quiet = True
                    if last_red:
                        try:
                            last_dt = datetime.fromisoformat(last_red)
                            if last_dt.tzinfo is None:
                                last_dt = last_dt.replace(tzinfo=timezone.utc)
                            enough_quiet = (now - last_dt) >= timedelta(minutes=quiet_minutes)
                        except ValueError:
                            enough_quiet = True
                    should_notify = enough_quiet and await self._is_barcello_cooldown_elapsed(config, guild_id, channel_id, "recovery", now)
                    is_recovery_notify = should_notify
        elif prev_color == "VERDE" and stored_color == "GIALLO":
            fresh = await self._get_recent_barcello_activity(channel_id, int(((config.get("event_driven") or {}).get("fresh_activity_minutes") or 5)))
            if not self._is_fresh_activity_ok(config, fresh):
                should_notify = False
                logger.info("barcello minor transition suppressed fresh-activity channel=%s transition=%s", channel_id, transition)
            else:
                should_notify = await self._is_barcello_cooldown_elapsed(config, guild_id, channel_id, "minor", now)
        elif prev_color and stored_color and {prev_color, stored_color} & {"ROSSO", "NERO"}:
            should_notify = await self._is_barcello_cooldown_elapsed(config, guild_id, channel_id, "major", now)
        else:
            should_notify = False

        if prev_score is not None and abs(score - prev_score) < min_score_delta_for_notify and prev_color == stored_color:
            should_notify = False

        if stored_color in {"ROSSO", "NERO"} and prev_color != stored_color:
            await self._database.update_barcello_recovery_state(
                guild_id,
                channel_id,
                recovery_armed=True,
                recovery_from=stored_color,
                recovery_armed_ts=now_iso,
            )
            recovery_armed = True
            recovery_from = stored_color
            logger.info("barcello recovery armed guild=%s channel=%s from=%s", guild_id, channel_id, stored_color)

        daily_state = await self._database.get_trigger_state(guild_id, channel_id, "barcello_daily")
        day_key = datetime.now(ROME_TZ).date().isoformat()
        if str(daily_state.get("date") or "") != day_key:
            daily_state = {"date": day_key, "counts": {}, "last_entered_ts": {}}
        counts = daily_state.get("counts") if isinstance(daily_state.get("counts"), dict) else {}
        last_entered_ts = daily_state.get("last_entered_ts") if isinstance(daily_state.get("last_entered_ts"), dict) else {}

        previous_same_state_ts = str(last_entered_ts.get(stored_color) or "")
        state_count_today = int(counts.get(stored_color) or 0) + 1
        counts[stored_color] = state_count_today
        last_entered_ts[stored_color] = now.isoformat()

        now_rome = now.astimezone(ROME_TZ)
        minute_seed = now_rome.strftime("%Y%m%d%H%M")
        time_bucket = self._get_time_bucket(now_rome, config)
        drama_label = self._get_drama_label(state_count_today, config)
        mood = await self._resolve_barcello_mood(guild_id, channel_id, config)

        last_in_state_human = ""
        if previous_same_state_ts:
            try:
                prev_same_state = datetime.fromisoformat(previous_same_state_ts)
                if prev_same_state.tzinfo is None:
                    prev_same_state = prev_same_state.replace(tzinfo=timezone.utc)
                delta = max(now - prev_same_state, timedelta())
                total_min = int(delta.total_seconds() // 60)
                if total_min < 120:
                    last_in_state_human = f"{total_min} minuti"
                elif total_min < 60 * 24 * 2:
                    last_in_state_human = f"{total_min // 60} ore"
                else:
                    last_in_state_human = f"{total_min // (60 * 24)} giorni"
            except ValueError:
                last_in_state_human = ""

        main_msg = self._render_barcello_transition(
            old=prev_color,
            new=stored_color,
            old_score=prev_score,
            new_score=score,
            cfg=config,
            guild_id=guild_id,
            channel_id=channel_id,
            mood=mood,
            time_bucket=time_bucket,
            drama_label=drama_label,
            state_count_today=state_count_today,
            last_in_state_human=last_in_state_human,
        )
        mod_block_text = ""
        if stored_color in {"ROSSO", "NERO"} and prev_color != stored_color:
            mod_key = "MOD_PING_ROSSO" if stored_color == "ROSSO" else "MOD_PING_NERO"
            selected_mod_template = self._select_barcello_template(
                config,
                channel_id,
                mood,
                time_bucket,
                drama_label,
                mod_key,
            )
            mod_template = self._resolve_template_value(
                selected_mod_template,
                seed_parts=(guild_id, channel_id, mod_key, mood, time_bucket, drama_label, minute_seed),
            )
            mod_role_id = str(config.get("mod_role_id") or "").strip()
            mod_mention = f"<@&{mod_role_id}>" if mod_role_id else ""
            mod_block_text = self._render_with_placeholders(mod_template, {"mod_mention": mod_mention}) if mod_template else mod_mention

        message_text = self._build_barcello_status_embed_description(
            main_msg=main_msg,
            old_score=prev_score,
            new_score=score,
            state_count_today=state_count_today,
            last_in_state_human=last_in_state_human,
            new=stored_color,
            mod_block_text=mod_block_text,
        )
        if should_notify:
            embed = discord.Embed(
                title="🫛 AGGIORNAMENTO BARCELLO",
                description=message_text,
                color=self._barcello_embed_color(stable_color),
            )
            attach_footer_meta(embed, service_name="triggers", used_local_processing=True)
            channel = self._bot.get_channel(int(channel_id))
            if channel and isinstance(channel, discord.abc.Messageable) and main_msg:
                await channel.send(embed=embed)
                cooldown_key = "recovery" if is_recovery_notify else ("minor" if stored_color in {"VERDE", "GIALLO"} else "major")
                await self._database.set_barcello_last_notified(guild_id, channel_id, cooldown_key.upper(), now_iso)
                if is_recovery_notify:
                    await self._database.update_barcello_recovery_state(
                        guild_id,
                        channel_id,
                        recovery_armed=False,
                        recovery_from=None,
                        recovery_armed_ts=None,
                        last_recovery_notified_ts=now_iso,
                    )
                    logger.info("barcello recovery disarmed guild=%s channel=%s", guild_id, channel_id)
            elif should_notify:
                logger.warning("barcello notify skipped: channel unavailable channel=%s", channel_id)
        else:
            logger.debug("barcello transition suppressed channel=%s transition=%s", channel_id, transition)

        await self._database.upsert_barcello_trigger_state(guild_id, channel_id, stored_color, score, now.isoformat())
        await self._database.set_barcello_last_seen_for_color(guild_id, channel_id, stored_color, now_iso)
        await self._database.set_trigger_state(
            guild_id,
            channel_id,
            "barcello_daily",
            {"date": day_key, "counts": counts, "last_entered_ts": last_entered_ts},
        )

    async def _get_recent_barcello_activity(self, channel_id: str, fresh_minutes: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=max(1, fresh_minutes))
        row = await self._database.fetchone(
            """
            SELECT COUNT(*) AS count, COUNT(DISTINCT author_id) AS authors, MAX(ts) AS last_message_ts
            FROM messages
            WHERE channel_id = ?
              AND ts >= ?
              AND ts <= ?
              AND COALESCE(is_deleted, 0) = 0
            """,
            (channel_id, start.isoformat(), now.isoformat()),
        )
        return {
            "count": int(row["count"] or 0) if row else 0,
            "authors": int(row["authors"] or 0) if row else 0,
            "last_message_ts": str(row["last_message_ts"] or "") if row else "",
        }

    async def _barcello_recovery_loop(self) -> None:
        while True:
            try:
                config = self._load_barcello_trigger_cfg_cached()
                recovery_cfg = config.get("recovery") if isinstance(config.get("recovery"), dict) else {}
                if not bool(recovery_cfg.get("enabled", True)):
                    await asyncio.sleep(60)
                    continue
                rows = await self._database.list_barcello_recovery_armed_channels()
                logger.info("barcello recovery loop checking channels=%s", len(rows))
                for row in rows:
                    await self._evaluate_barcello_channel(str(row["guild_id"]), str(row["channel_id"]), reason="recovery_loop", allow_recovery=True)
                await asyncio.sleep(max(60, int(recovery_cfg.get("poll_seconds") or 300)))
            except Exception:  # noqa: BLE001
                logger.exception("barcello recovery loop failed")
                await asyncio.sleep(60)

    def _is_fresh_activity_ok(self, cfg: dict[str, Any], activity: dict[str, Any]) -> bool:
        event_cfg = cfg.get("event_driven") if isinstance(cfg.get("event_driven"), dict) else {}
        min_recent_messages = int(event_cfg.get("min_recent_messages") or 4)
        min_recent_authors = int(event_cfg.get("min_recent_authors") or 2)
        max_age_seconds = int(event_cfg.get("max_last_message_age_seconds") or 120)
        count = int(activity.get("count") or 0)
        authors = int(activity.get("authors") or 0)
        last_ts = str(activity.get("last_message_ts") or "")
        age_ok = True
        if last_ts:
            try:
                last_dt = datetime.fromisoformat(last_ts)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                age_ok = (datetime.now(timezone.utc) - last_dt) <= timedelta(seconds=max_age_seconds)
            except ValueError:
                age_ok = True
        return count >= min_recent_messages and authors >= min_recent_authors and age_ok

    async def _is_barcello_cooldown_elapsed(self, cfg: dict[str, Any], guild_id: str, channel_id: str, bucket: str, now: datetime) -> bool:
        cooldown_cfg = cfg.get("cooldown_minutes")
        if isinstance(cooldown_cfg, dict):
            cooldown_minutes = int(cooldown_cfg.get(bucket) or cooldown_cfg.get("minor") or 0)
        else:
            cooldown_minutes = int(cooldown_cfg or 0)
        if cooldown_minutes <= 0:
            return True
        last_notified = await self._database.get_barcello_last_notified(guild_id, channel_id, bucket.upper())
        if not last_notified:
            return True
        try:
            last_dt = datetime.fromisoformat(last_notified)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        allowed = now - last_dt >= timedelta(minutes=cooldown_minutes)
        if not allowed:
            logger.info("barcello cooldown blocks notify guild=%s channel=%s bucket=%s", guild_id, channel_id, bucket)
        return allowed

    def _load_barcello_trigger_cfg_cached(self) -> dict[str, Any]:
        path = self._barcello_trigger_cfg_path
        try:
            mtime = os.stat(path).st_mtime
            self._barcello_trigger_cfg_missing_warned = False
        except FileNotFoundError:
            if self._barcello_trigger_cfg is None:
                cfg = load_json_file(path)
                self._barcello_trigger_cfg = cfg
                self._refresh_barcello_window_override_cache(cfg)
                return cfg
            if not self._barcello_trigger_cfg_missing_warned:
                logger.warning("barcello trigger config missing path=%s, using last valid config", path)
                self._barcello_trigger_cfg_missing_warned = True
            return self._barcello_trigger_cfg

        if self._barcello_trigger_cfg is None or self._barcello_trigger_cfg_mtime != mtime:
            cfg = load_json_file(path)
            if not cfg and self._barcello_trigger_cfg is not None:
                logger.warning("barcello trigger config invalid/empty path=%s, keeping last valid config", path)
                return self._barcello_trigger_cfg
            self._barcello_trigger_cfg = cfg
            self._barcello_trigger_cfg_mtime = mtime
            self._refresh_barcello_window_override_cache(cfg)
        return self._barcello_trigger_cfg or {}

    def _refresh_barcello_window_override_cache(self, cfg: dict[str, Any]) -> None:
        raw = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
        fingerprint = hashlib.sha1(raw.encode("utf-8")).hexdigest()
        if self._barcello_window_override_cache_fingerprint != fingerprint:
            self._barcello_window_override_cache.clear()
            self._barcello_window_override_cache_fingerprint = fingerprint

    def _get_effective_window_minutes(self, *, cfg: dict[str, Any], channel_id: str, default_window: int) -> int:
        if channel_id in self._barcello_window_override_cache:
            return self._barcello_window_override_cache[channel_id]
        window = resolve_window_minutes(
            channel_id,
            default_window=default_window,
            trigger_config=cfg,
        )
        self._barcello_window_override_cache[channel_id] = window
        return window

    def _apply_hysteresis(self, prev_color: str | None, raw_color: str | None, score: int) -> str | None:
        _ = (prev_color, score)
        return raw_color

    async def _handle_phrases(self, envelope: EventEnvelope) -> None:
        assert envelope.guild_id and envelope.channel_id
        globally_enabled = await self._database.get_trigger_enabled_global(envelope.guild_id, "frasi")
        if not globally_enabled and not await self._database.get_trigger_enabled_any_channel(envelope.guild_id, "frasi"):
            return
        phrases = await self._database.get_matching_phrases_guild(envelope.guild_id)
        content = envelope.content or ""
        winning_by_text: dict[str, dict[str, object]] = {}
        for phrase in phrases:
            if not self._phrase_matches(content, phrase):
                continue
            # Legacy compat: stessa frase poteva essere inserita in più canali.
            # Manteniamo i record ma per un singolo messaggio rispondiamo una sola volta,
            # scegliendo deterministicamente la riga col min id.
            key = f"{str(phrase.get('phrase') or '').casefold()}|{str(phrase.get('match_mode') or '').upper()}|{int(bool(phrase.get('case_sensitive')))}"
            current = winning_by_text.get(key)
            if current is None or int(phrase.get("id") or 0) < int(current.get("id") or 0):
                winning_by_text[key] = phrase

        if not winning_by_text:
            return
        winner = min(winning_by_text.values(), key=lambda row: int(row.get("id") or 0))
        await self._reply_phrase(envelope, winner)

    async def _reply_phrase(self, envelope: EventEnvelope, phrase: dict[str, object]) -> None:
        if self._bot is None or not envelope.channel_id:
            return
        channel = self._bot.get_channel(int(envelope.channel_id))
        if channel is None or not isinstance(channel, discord.TextChannel):
            return
        phrase_id = int(phrase["id"])
        ts = datetime.now(timezone.utc).isoformat()
        message_id = str(envelope.meta.get("message_id") or "")
        author_id = str(envelope.author_id or "")
        target_message: discord.Message | None = None
        if message_id:
            try:
                target_message = await channel.fetch_message(int(message_id))
            except (discord.NotFound, discord.HTTPException, ValueError):
                target_message = None
        if not self._is_phrase_role_allowed(phrase, channel, target_message, author_id):
            logger.debug("Phrase trigger ignored: missing required role", extra={"phrase_id": phrase_id, "author_id": author_id})
            return

        stats_before = await self._database.get_phrase_user_stats(phrase_id, author_id) if author_id else {}
        if self._is_phrase_in_cooldown(phrase, stats_before):
            logger.debug("Phrase trigger ignored: cooldown active", extra={"phrase_id": phrase_id, "author_id": author_id})
            return

        author_name = await self._resolve_phrase_author_name(envelope, channel, target_message)

        state = await self._database.get_trigger_state_any_channel(envelope.guild_id, "frasi")
        previous_seen = self._build_last_seen_values(phrase.get("last_seen_ts"))

        previous_count = int(stats_before.get("count") or 0)
        count_user = previous_count + 1 if author_id else 0
        template_kind = "FIRST" if previous_count <= 0 else "DEFAULT"

        global_milestones_enabled = bool(state.get("global_milestones_enabled", False))
        active_milestone = {}
        if global_milestones_enabled and count_user > 0:
            active_milestone = await self._database.get_trigger_phrase_global_milestone(envelope.guild_id, count_user)
        milestone_template = str(active_milestone.get("template_text") or "")
        if milestone_template:
            template_kind = "MILESTONE"

        global_milestones = await self._database.list_trigger_phrase_global_milestones(envelope.guild_id)
        next_milestone_value = next(
            (
                int(row.get("threshold_count") or 0)
                for row in global_milestones
                if int(row.get("threshold_count") or 0) > count_user
            ),
            None,
        )

        custom_user_phrase = ""
        if author_id:
            custom_user_phrase = await self._database.get_trigger_phrase_global_user_custom_text(envelope.guild_id, author_id)

        template = self._resolve_phrase_template(
            state,
            kind=template_kind,
            milestone_template=milestone_template,
        )

        if author_id:
            await self._database.increment_phrase_user_stats(phrase_id, author_id, ts, message_id)
        values = {
            "author": f"<@{author_id}>" if author_id else "",
            "author_name": author_name,
            "phrase": str(phrase.get("phrase") or ""),
            "count_user_prev": str(previous_count),
            "count_user": str(count_user),
            "last_seen_human": previous_seen["human"],
            "last_seen_dt": previous_seen["dt"],
            "custom_user_phrase": custom_user_phrase,
            "milestone": str(active_milestone.get("threshold_count") or "") if active_milestone else "",
            "next_milestone": str(next_milestone_value) if next_milestone_value is not None else "",
            "remaining_to_next_milestone": (
                str(max(0, next_milestone_value - count_user)) if next_milestone_value is not None else ""
            ),
        }

        rendered_text = str(phrase.get("phrase") or "")
        try:
            candidate = self._render_phrase_template(template, values).strip()
            if candidate:
                rendered_text = candidate
            else:
                raise ValueError("empty rendered phrase template")
        except Exception:
            logger.exception("Failed to render phrase template; using built-in fallback", extra={"phrase_id": phrase_id})
            try:
                fallback = self._render_phrase_template(PHRASE_FALLBACK_TEMPLATES[template_kind], values).strip()
                if fallback:
                    rendered_text = fallback
            except Exception:
                logger.exception("Failed to render phrase fallback template; using raw phrase", extra={"phrase_id": phrase_id})

        color = self._discord_color_from_phrase(phrase)
        embed = discord.Embed(
            title="💬 FRASI ICONICHE",
            description=rendered_text,
            color=color,
        )
        attach_footer_meta(embed, service_name="triggers", used_local_processing=True)

        if target_message is not None:
            await target_message.reply(embed=embed)
        else:
            await channel.send(embed=embed)
        await self._database.update_phrase_last_seen(phrase_id, ts, message_id)

    def _is_phrase_role_allowed(
        self,
        phrase: dict[str, object],
        channel: discord.TextChannel,
        message: discord.Message | None,
        author_id: str,
    ) -> bool:
        allowed_raw = phrase.get("allowed_role_ids")
        if not isinstance(allowed_raw, list) or not allowed_raw:
            return True
        allowed_ids = {str(role_id).strip() for role_id in allowed_raw if str(role_id).strip()}
        if not allowed_ids:
            return True
        if not author_id or not author_id.isdigit():
            return False

        member = getattr(message, "author", None)
        if member is None or not hasattr(member, "roles"):
            member = channel.guild.get_member(int(author_id))
        if member is None or not hasattr(member, "roles"):
            return False
        member_roles = {str(getattr(role, "id", "")) for role in getattr(member, "roles", [])}
        return bool(member_roles.intersection(allowed_ids))

    def _is_phrase_in_cooldown(self, phrase: dict[str, object], stats_before: dict[str, object]) -> bool:
        cooldown_raw = phrase.get("cooldown_seconds")
        if cooldown_raw in (None, ""):
            return False
        try:
            cooldown_seconds = int(cooldown_raw)
        except (TypeError, ValueError):
            return False
        if cooldown_seconds <= 0:
            return False
        last_seen_raw = str(stats_before.get("last_seen_ts") or "").strip()
        if not last_seen_raw:
            return False
        try:
            last_seen = datetime.fromisoformat(last_seen_raw)
        except ValueError:
            return False
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_seen).total_seconds()
        return elapsed < cooldown_seconds


    def _discord_color_from_phrase(self, phrase: dict[str, object]) -> discord.Color:
        raw = str(phrase.get("embed_color") or "").strip()
        if raw:
            value = raw[1:] if raw.startswith("#") else raw
            try:
                return discord.Color(int(value, 16))
            except ValueError:
                pass
        return discord.Color.gold()

    async def _resolve_phrase_author_name(
        self,
        envelope: EventEnvelope,
        channel: discord.TextChannel,
        message: discord.Message | None = None,
    ) -> str:
        message_author = getattr(message, "author", None)
        if message_author is not None:
            display_name = getattr(message_author, "display_name", None)
            if display_name:
                return str(display_name)
            username = getattr(message_author, "name", None)
            if username:
                return str(username)

        meta_author_name = str(envelope.meta.get("author_name") or "").strip()
        if meta_author_name:
            return meta_author_name

        author_id = str(envelope.author_id or "")
        if not author_id:
            return "utente"
        cached = await self._database.fetch_user_display_name(guild_id=str(channel.guild.id), user_id=author_id)
        if cached:
            return str(cached)
        if author_id.isdigit():
            member = channel.guild.get_member(int(author_id))
            if member is not None:
                return member.display_name
        return author_id

    def _resolve_phrase_template(
        self,
        state: dict[str, object],
        *,
        kind: str,
        milestone_template: str = "",
    ) -> str:
        templates: dict[str, object] = {}
        if isinstance(state.get("templates"), dict):
            templates = dict(state["templates"])
        selected = milestone_template or templates.get(kind) or PHRASE_FALLBACK_TEMPLATES.get(kind, PHRASE_FALLBACK_TEMPLATES["DEFAULT"])
        return str(selected)

    def _build_last_seen_values(self, last_seen_ts: object) -> dict[str, str]:
        if not last_seen_ts:
            return {"human": "mai", "dt": ""}
        try:
            last_seen = datetime.fromisoformat(str(last_seen_ts))
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            delta = max(now - last_seen, timedelta())
            total_minutes = int(delta.total_seconds() // 60)
            if total_minutes < 120:
                human = f"{total_minutes} minuti"
            elif total_minutes < 60 * 24 * 2:
                human = f"{total_minutes // 60} ore"
            else:
                human = f"{total_minutes // (60 * 24)} giorni"
            dt_text = last_seen.astimezone(ROME_TZ).strftime("%d/%m/%Y %H:%M")
            return {"human": human, "dt": dt_text}
        except ValueError:
            return {"human": "un po' di tempo", "dt": ""}

    def _render_phrase_template(self, template: str, values: dict[str, str]) -> str:
        rendered = template
        for placeholder in PHRASE_PLACEHOLDERS:
            key = placeholder[1:-1]
            rendered = rendered.replace(placeholder, values.get(key, ""))
        return rendered

    def _phrase_matches(self, content: str, phrase: dict[str, object]) -> bool:
        raw_phrase = str(phrase.get("phrase") or "")
        if not raw_phrase:
            return False
        case_sensitive = bool(phrase.get("case_sensitive"))
        mode = str(phrase.get("match_mode") or "CONTAINS").upper()
        haystack = content if case_sensitive else content.lower()
        needle = raw_phrase if case_sensitive else raw_phrase.lower()
        if mode == "EXACT":
            return haystack.strip() == needle.strip()
        if mode == "REGEX":
            try:
                flags = 0 if case_sensitive else re.IGNORECASE
                return re.search(raw_phrase, content, flags=flags) is not None
            except re.error:
                return False
        return needle in haystack

    def _normalize_barcello_color(self, color: str | None) -> str | None:
        if color is None:
            return None
        normalized = str(color).strip().upper()
        if not normalized:
            return None
        english_to_italian = {"GREEN": "VERDE", "YELLOW": "GIALLO", "RED": "ROSSO", "BLACK": "NERO"}
        canonical = {"VERDE", "GIALLO", "ROSSO", "NERO"}
        mapped = english_to_italian.get(normalized, normalized)
        if mapped in canonical:
            return mapped
        return normalized

    def _apply_hysteresis(self, prev_color: str | None, raw_color: str, score: int) -> str:
        if prev_color is None:
            return raw_color
        if prev_color == raw_color:
            return prev_color

        thresholds: dict[tuple[str, str], int] = {
            ("VERDE", "GIALLO"): 57,
            ("GIALLO", "VERDE"): 63,
            ("GIALLO", "ROSSO"): 37,
            ("ROSSO", "GIALLO"): 43,
            ("ROSSO", "NERO"): 17,
            ("NERO", "ROSSO"): 23,
        }
        threshold = thresholds.get((prev_color, raw_color))
        if threshold is None:
            return raw_color

        increase_transitions = {("GIALLO", "VERDE"), ("ROSSO", "GIALLO"), ("NERO", "ROSSO")}
        if (prev_color, raw_color) in increase_transitions:
            return raw_color if score >= threshold else prev_color
        return raw_color if score <= threshold else prev_color

    def _barcello_embed_color(self, color: str) -> discord.Color:
        normalized_color = self._normalize_barcello_color(color) or ""
        mapping = {
            "VERDE": discord.Color.green(),
            "GIALLO": discord.Color.gold(),
            "ROSSO": discord.Color.red(),
            "NERO": discord.Color.dark_grey(),
        }
        return mapping.get(normalized_color, discord.Color.blurple())

    def _format_barcello_last_seen_dt(self, last_seen_ts: str | None) -> str:
        if not last_seen_ts:
            return "mai"
        try:
            dt = datetime.fromisoformat(last_seen_ts)
        except ValueError:
            return "mai"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ROME_TZ).strftime("%d/%m/%Y %H:%M")

    def _format_barcello_last_seen_human(self, last_seen_ts: str | None, now_utc: datetime) -> str:
        if not last_seen_ts:
            return "mai"
        try:
            then = datetime.fromisoformat(last_seen_ts)
        except ValueError:
            return "mai"
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        delta_seconds = int((now_utc - then).total_seconds())
        if delta_seconds < 0:
            delta_seconds = 0
        total_minutes = delta_seconds // 60
        if total_minutes < 120:
            return f"{total_minutes} minuti"
        total_hours = total_minutes // 60
        if total_hours < 48:
            return f"{total_hours} ore"
        total_days = total_hours // 24
        return f"{total_days} giorni"

    def _pick_template_value(self, value: Any) -> str:
        if isinstance(value, list):
            options = [v for v in value if isinstance(v, str) and v.strip()]
            return random.choice(options) if options else ""
        if isinstance(value, str):
            return value
        return ""

    def _render_barcello_transition(
        self,
        old: str | None,
        new: str,
        old_score: int | None,
        new_score: int,
        cfg: dict[str, object],
        guild_id: str,
        channel_id: str,
        mood: str,
        time_bucket: str,
        drama_label: str,
        state_count_today: int,
        last_in_state_human: str,
    ) -> str:
        worsening = {"VERDE": 0, "GIALLO": 1, "ROSSO": 2, "NERO": 3}
        italian_to_english = {"VERDE": "GREEN", "GIALLO": "YELLOW", "ROSSO": "RED", "NERO": "BLACK"}
        values = {
            "old": old or "",
            "new": new,
            "old_score": "" if old_score is None else str(old_score),
            "new_score": str(new_score),
            "state_count_today": str(state_count_today),
            "last_in_state_human": last_in_state_human,
            "mood": mood,
            "time_bucket": time_bucket,
            "drama_label": drama_label,
        }

        minute_seed = datetime.now(ROME_TZ).strftime("%Y%m%d%H%M")

        def render_key(key: str) -> str | None:
            selected = self._select_barcello_template(cfg, channel_id, mood, time_bucket, drama_label, key)
            message_template = self._resolve_template_value(
                selected,
                seed_parts=(guild_id, channel_id, key, mood, time_bucket, drama_label, minute_seed),
            )
            if not message_template:
                return None
            return self._render_with_placeholders(message_template, values)

        if old is None:
            return render_key("INIT") or f"📌 Barcello ora {new} (score {new_score})"

        severity_new = worsening.get(new, 99)
        severity_old = worsening.get(old, 99)

        if old != new:
            key_candidates = [f"{old}->{new}"]
            old_en = italian_to_english.get(old, old)
            new_en = italian_to_english.get(new, new)
            if f"{old_en}->{new_en}" not in key_candidates:
                key_candidates.append(f"{old_en}->{new_en}")
            if state_count_today == 1:
                key_candidates.append(f"{new}_FIRST_TODAY")
            for key in key_candidates:
                exact_template = render_key(key)
                if exact_template:
                    return exact_template

        if severity_new > severity_old:
            return render_key("WORSEN") or f"⚠️ Barcello peggiora: {old} → {new} ({old_score}→{new_score})."
        if severity_new < severity_old:
            return render_key("IMPROVE") or f"✅ Barcello migliora: {old} → {new} ({old_score}→{new_score})."
        return render_key("SAME") or f"Barcello aggiornato: {new_score}."

    def _build_barcello_status_embed_description(
        self,
        *,
        main_msg: str,
        old_score: int | None,
        new_score: int,
        state_count_today: int,
        last_in_state_human: str,
        new: str,
        mod_block_text: str,
    ) -> str:
        sections: list[str] = []
        if main_msg:
            sections.append(main_msg)

        if mod_block_text and new in {"ROSSO", "NERO"}:
            sections.append(mod_block_text)

        if old_score is None:
            sections.append(f"🫀 **PUNTI SALUTE:** {new_score}/100")
        else:
            sections.append(f"🫀 **PUNTI SALUTE:** {old_score}→{new_score}/100")

        if state_count_today >= 2 and last_in_state_human:
            sections.append(
                (
                    f"📊 **Oggi:** {state_count_today}ª volta che il Barcy diventa {new}.\n"
                    f"⏱️ **Ultima:** {last_in_state_human} fa."
                )
            )

        return "\n\n".join(section for section in sections if section.strip())

    def _render_with_placeholders(self, text: str, placeholders: dict[str, str]) -> str:
        return re.sub(r"\{([a-zA-Z0-9_]+)\}", lambda match: placeholders.get(match.group(1), match.group(0)), text)

    def _resolve_template_value(self, value: object, *, seed_parts: tuple[str, ...]) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            options = [item for item in value if isinstance(item, str) and item.strip()]
            if not options:
                return ""
            seed = "|".join(seed_parts)
            hashed = hashlib.sha256(seed.encode("utf-8")).hexdigest()
            index = int(hashed[:8], 16) % len(options)
            return options[index]
        return ""

    def _get_time_bucket(self, now_rome: datetime, cfg: dict[str, object]) -> str:
        default_buckets = {
            "night": {"start": 0, "end": 6},
            "morning": {"start": 6, "end": 12},
            "afternoon": {"start": 12, "end": 18},
            "evening": {"start": 18, "end": 24},
        }
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
            first_key = next(iter(buckets.keys()))
            return str(first_key)
        return "unknown"

    def _get_drama_label(self, state_count_today: int, cfg: dict[str, object]) -> str:
        raw_tiers = cfg.get("dramatic_tiers")
        tiers = raw_tiers if isinstance(raw_tiers, list) else [{"min_count_today": 1, "label": "t1"}]
        winner = "t1"
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            minimum = tier.get("min_count_today")
            label = tier.get("label")
            if isinstance(minimum, int) and isinstance(label, str) and state_count_today >= minimum:
                winner = label
        return winner

    async def _resolve_barcello_mood(self, guild_id: str, channel_id: str, cfg: dict[str, object]) -> str:
        default_mood = str(cfg.get("mood_default") or "chill")
        channel_cfg = cfg.get("channels") if isinstance(cfg.get("channels"), dict) else {}
        selected_channel = channel_cfg.get(channel_id) if isinstance(channel_cfg.get(channel_id), dict) else {}
        channel_default = selected_channel.get("mood_default") if isinstance(selected_channel.get("mood_default"), str) else None
        stored_state = await self._database.get_trigger_state(guild_id, channel_id, "barcello_mood")
        stored_mood = stored_state.get("mood") if isinstance(stored_state.get("mood"), str) else None
        return str(stored_mood or channel_default or default_mood)

    def _select_barcello_template(
        self,
        cfg: dict[str, object],
        channel_id: str,
        mood: str,
        time_bucket: str,
        drama_label: str,
        key: str,
    ) -> object | None:
        channels = cfg.get("channels") if isinstance(cfg.get("channels"), dict) else {}
        channel_cfg = channels.get(channel_id) if isinstance(channels.get(channel_id), dict) else None
        moods = cfg.get("moods") if isinstance(cfg.get("moods"), dict) else {}
        mood_cfg = moods.get(mood) if isinstance(moods.get(mood), dict) else None

        candidates: list[object] = []
        if channel_cfg:
            channel_moods = channel_cfg.get("moods") if isinstance(channel_cfg.get("moods"), dict) else {}
            channel_mood_cfg = channel_moods.get(mood) if isinstance(channel_moods.get(mood), dict) else None
            candidates.extend(
                self._collect_barcello_candidates(channel_mood_cfg, key=key, time_bucket=time_bucket, drama_label=drama_label)
            )
            candidates.extend(self._collect_barcello_candidates(channel_cfg, key=key, time_bucket=time_bucket, drama_label=drama_label))

        candidates.extend(self._collect_barcello_candidates(mood_cfg, key=key, time_bucket=time_bucket, drama_label=drama_label))
        templates = cfg.get("templates") if isinstance(cfg.get("templates"), dict) else {}
        candidates.append(templates.get(key))

        for candidate in candidates:
            if isinstance(candidate, str):
                if candidate.strip():
                    return candidate
            elif isinstance(candidate, list):
                if any(isinstance(item, str) and item.strip() for item in candidate):
                    return candidate
        return None

    def _collect_barcello_candidates(self, base: object, *, key: str, time_bucket: str, drama_label: str) -> list[object]:
        if not isinstance(base, dict):
            return []

        candidates: list[object] = []
        templates = base.get("templates") if isinstance(base.get("templates"), dict) else {}
        time = base.get("time") if isinstance(base.get("time"), dict) else {}
        drama = base.get("drama") if isinstance(base.get("drama"), dict) else {}

        time_bucket_cfg = time.get(time_bucket) if isinstance(time.get(time_bucket), dict) else {}
        time_templates = time_bucket_cfg.get("templates") if isinstance(time_bucket_cfg.get("templates"), dict) else {}
        time_drama = time_bucket_cfg.get("drama") if isinstance(time_bucket_cfg.get("drama"), dict) else {}
        time_drama_cfg = time_drama.get(drama_label) if isinstance(time_drama.get(drama_label), dict) else {}
        time_drama_templates = (
            time_drama_cfg.get("templates") if isinstance(time_drama_cfg.get("templates"), dict) else {}
        )

        drama_cfg = drama.get(drama_label) if isinstance(drama.get(drama_label), dict) else {}
        drama_templates = drama_cfg.get("templates") if isinstance(drama_cfg.get("templates"), dict) else {}

        candidates.append(time_drama_templates.get(key))
        candidates.append(drama_templates.get(key))
        candidates.append(time_templates.get(key))
        candidates.append(templates.get(key))
        return candidates

    async def _poll_insights(self) -> None:
        if self._bot is None:
            return
        rows = await self._database.list_enabled_trigger_channels("insights")
        now = datetime.now(timezone.utc)
        config = await self._community_insights.get_config(await self._database.get_setting("community_insights.config"))
        interval_minutes = max(10, int(config.get("interval_minutes") or 180))
        min_reuse_ts = (now - timedelta(days=7)).isoformat()
        for row in rows:
            guild_id = str(row["guild_id"])
            channel_id = str(row["channel_id"])
            state = await self._database.get_trigger_state(guild_id, channel_id, "insights")
            last_post_at = state.get("last_post_at")
            if last_post_at:
                try:
                    if now - datetime.fromisoformat(str(last_post_at)) < timedelta(minutes=interval_minutes):
                        continue
                except ValueError:
                    pass
            messages = await self._database.list_recent_messages_for_hobbies(guild_id, channel_id, limit=60)
            heuristics = self._community_insights.extract_hobbies_from_messages(messages)
            ai_extracted = await self._community_insights.extract_hobbies_ai(messages)
            for entry in [*heuristics, *ai_extracted]:
                if entry.get("hobby") and entry.get("source_message_id"):
                    await self._database.insert_user_hobby(
                        guild_id=guild_id,
                        user_id=str(entry.get("user_id") or ""),
                        user_name=str(entry.get("user_name") or "utente"),
                        hobby=str(entry.get("hobby") or ""),
                        source_channel_id=str(entry.get("source_channel_id") or channel_id),
                        source_message_id=str(entry.get("source_message_id") or ""),
                        source_created_at=str(entry.get("source_created_at") or now.isoformat()),
                    )
            candidate = await self._database.get_next_hobby(guild_id, channel_id, min_reuse_ts)
            if not candidate:
                continue
            jump_url = f"https://discord.com/channels/{guild_id}/{candidate['source_channel_id']}/{candidate['source_message_id']}"
            dt = self._format_italian_datetime(str(candidate.get("source_created_at") or now.isoformat()))
            text = self._community_insights.render_template(
                str(config.get("template") or ""),
                {
                    "user_name": str(candidate.get("user_name") or "utente"),
                    "hobby": str(candidate.get("hobby") or ""),
                    "dt": dt,
                    "jump_url": jump_url,
                },
            )
            channel = self._bot.get_channel(int(channel_id))
            if channel and isinstance(channel, discord.abc.Messageable):
                await channel.send(text)
                await self._database.set_trigger_state(guild_id, channel_id, "insights", {"last_post_at": now.isoformat()})
                await self._database.mark_hobby_used(
                    guild_id,
                    str(candidate.get("user_id") or ""),
                    str(candidate.get("hobby") or ""),
                    str(candidate.get("source_message_id") or ""),
                )

    async def _handle_qna(
        self,
        *,
        scope: str,
        guild_id: str,
        channel_id: str,
        question: str,
        source: discord.Interaction | discord.Message | None = None,
    ) -> dict[str, object] | None:
        normalized_question = self._normalize_question(question)
        cache_scope = "global" if scope == "global" else scope
        cache_channel = channel_id if cache_scope == "channel" else "global"
        cache_fragment = "semantic_v4"
        target_ids_fragment = "all"
        session_signature = "nosession"
        cache_key = f"qna:{cache_scope}:{cache_channel}:{target_ids_fragment}:{cache_fragment}:{session_signature}:{normalized_question}"
        cached = await self._database.get_cache(cache_key)
        if cached is not None:
            logger.info("qna cache hit scope=%s channel_id=%s", scope, channel_id)
            cached_text = str(cached)
            cached_proofs: list[dict[str, str]] = []
            try:
                parsed_cached = json.loads(cached_text)
                if isinstance(parsed_cached, dict):
                    cached_text = str(parsed_cached.get("answer") or "")
                    parsed_proofs = parsed_cached.get("proofs")
                    if isinstance(parsed_proofs, list):
                        cached_proofs = [item for item in parsed_proofs if isinstance(item, dict)]
            except json.JSONDecodeError:
                pass
            return {
                "can_answer": True,
                "answer": cached_text,
                "refusal_reason": None,
                "evidence_pack": cached_proofs,
                "answer_mode": "semantic_plain",
                "response_origin": "local_backend",
            }

        if scope == "global":
            text_answer = await self._ask_general_answer(question)
            if text_answer:
                await self._database.set_cache(cache_key, text_answer, 7 * 24 * 3600)
                return {"can_answer": True, "answer": text_answer, "refusal_reason": None, "evidence_pack": [], "answer_mode": "plain", "response_origin": "remote_ai"}
            return None

        try:
            channel_answer = await self._qna_query_engine.answer(
                guild_id=guild_id,
                channel_id=channel_id,
                question=question,
                source=source,
            )
        except Exception:  # noqa: BLE001
            logger.exception("qna_query_engine_failed")
            return None

        if isinstance(channel_answer, QnaAnswerResult):
            channel_answer_text = channel_answer.answer_text
            channel_proofs = channel_answer.proofs
        elif isinstance(channel_answer, dict):
            channel_answer_text = str(channel_answer.get("answer_text") or "")
            raw_proofs = channel_answer.get("proofs")
            channel_proofs = [item for item in raw_proofs if isinstance(item, dict)] if isinstance(raw_proofs, list) else []
        else:
            channel_answer_text = str(channel_answer or "")
            channel_proofs = []

        if not channel_answer_text:
            return None

        cache_payload = json.dumps({"answer": channel_answer_text, "proofs": channel_proofs}, ensure_ascii=False)
        await self._database.set_cache(cache_key, cache_payload, 45 * 60)
        return {
            "can_answer": True,
            "answer": channel_answer_text,
            "refusal_reason": None,
            "evidence_pack": channel_proofs,
            "answer_mode": "semantic_plain",
            "response_origin": "local_backend",
        }

    def _append_qna_proofs_section(
        self,
        answer_text: str,
        proofs: list[dict[str, str]],
        *,
        max_links: int = 4,
    ) -> str:
        base_text = (answer_text or "").strip()
        if not base_text or not proofs:
            return base_text

        unique_proofs: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for proof in proofs:
            if not isinstance(proof, dict):
                continue
            jump_url = str(proof.get("jump_url") or "").strip()
            if not self._is_valid_jump_url(jump_url) or jump_url in seen_urls:
                continue
            created_at_iso = str(proof.get("created_at_iso") or "").strip()
            if not created_at_iso:
                continue
            seen_urls.add(jump_url)
            unique_proofs.append({"jump_url": jump_url, "created_at_iso": created_at_iso})

        if not unique_proofs:
            return base_text

        unique_proofs.sort(key=lambda item: str(item.get("created_at_iso") or ""), reverse=True)
        capped_max = max(1, min(max_links, len(unique_proofs)))
        for links_count in range(capped_max, 0, -1):
            lines: list[str] = ["", "**🧾 Prove:**"]
            valid_links = 0
            for item in unique_proofs[:links_count]:
                ts = self._format_proof_timestamp(str(item.get("created_at_iso") or ""))
                jump_url = str(item.get("jump_url") or "").strip()
                if not ts:
                    continue
                lines.append(f"• [{ts}]({jump_url})")
                valid_links += 1
            if valid_links == 0:
                continue
            candidate = base_text + "\n".join(lines)
            if len(candidate) <= 3900:
                return candidate
        return base_text

    async def _decide_qna_scope(self, question: str) -> str:
        q = question.lower()
        channel_indicators = [
            "nel canale",
            "qui",
            "oggi",
            "scrive",
            "partecipa",
            "barcella",
            "in chat",
            "in questa stanza",
            "@",
        ]
        global_indicators = ["cos'è", "chi è", "come si fa", "definisci", "spiegami"]
        channel_score = sum(1 for token in channel_indicators if token in q)
        global_score = sum(1 for token in global_indicators if token in q)
        if channel_score > 0 and global_score == 0:
            return "channel"
        if global_score > 0 and channel_score == 0:
            return "global"
        if channel_score > 0 and global_score > 0:
            return "mixed"
        classified = await self._classify_scope_with_ai(question)
        return classified if classified in {"channel", "global", "mixed"} else "mixed"

    async def _classify_scope_with_ai(self, question: str) -> str:
        payload = json.dumps(
            {
                "task": "qna_scope_classification",
                "question": question,
                "reply_only_json": True,
                "output_schema": {"scope": "channel|global|mixed", "confidence": 0.0, "reason": "string"},
            },
            ensure_ascii=False,
        )
        answer = await self._ask_ai_json(payload)
        if not answer:
            return "mixed"
        scope = str(answer.get("scope") or "mixed").strip().lower()
        return scope

    def _classify_general_query_type(self, question: str) -> str:
        q = (question or "").lower()
        if any(token in q for token in ["meteo", "temperatura", "pioggia", "vento", "prevision"]):
            return "weather"
        if any(token in q for token in ["notizie", "news", "ultime", "breaking", "oggi nel mondo"]):
            return "news"
        if any(token in q for token in ["prezzo", "costo", "quotazione", "btc", "bitcoin", "euro oggi"]):
            return "prices"
        if any(token in q for token in ["risultato", "partita", "classifica", "serie a", "champions"]):
            return "sports"
        if any(token in q for token in ["evento", "concerto", "fiera", "programma", "quando si tiene"]):
            return "events"
        return "generic"

    def _needs_web_search(self, question: str) -> bool:
        query_type = self._classify_general_query_type(question)
        if query_type in {"weather", "news", "prices", "sports", "events"}:
            return True
        q = (question or "").lower()
        realtime_tokens = ["oggi", "domani", "adesso", "in tempo reale", "attuale", "ultim", "live"]
        return any(token in q for token in realtime_tokens)

    async def _ask_general_answer(self, question: str, history: list[dict[str, str]] | None = None) -> str | None:
        query_type = self._classify_general_query_type(question)
        use_web = self._needs_web_search(question)
        logger.info("general_llm_web=%s query_type=%s", use_web, query_type)

        if use_web:
            try:
                text_web = await self._ai.ask_for_task_with_web("summary", question, self._general_persona_system_prompt(), history or [])
                if text_web:
                    return text_web
            except Exception:  # noqa: BLE001
                logger.exception("general_llm web_search failed", extra={"query_type": query_type})

            offline = await self._ask_general_llm(question, history=history)
            if not offline:
                return None
            return f"{offline}\n\n_(Nota: non sono riuscito a verificare fonti web affidabili in tempo reale.)_"

        return await self._ask_general_llm(question, history=history)

    def _general_persona_system_prompt(self) -> str:
        return (
            "Sei Barcellometro, assistente della community con tono empatico, simpatico e cricetoso. "
            "Rispondi in italiano con Markdown compatibile Discord: **grassetto**, elenchi puntati e righe brevi. "
            "Usa 4-10 emoji pertinenti quando utile, evita muri di testo e preferisci 3-5 punti chiari. "
            "Struttura consigliata: apertura calorosa breve, punti essenziali, chiusura con aggancio naturale. "
            "Se usi dati dal web cita le fonti in modo chiaro."
        )

    async def _ask_general_llm(self, question: str, history: list[dict[str, str]] | None = None) -> str | None:
        if self._ai is None or not self._ai.is_enabled() or self._ai.client() is None:
            return None
        model = self._ai.get_model_config("summary") or "unknown"
        provider = (model.split(":", 1)[0] if ":" in model else "unknown")
        logger.info("qna_llm_called=%s model=%s", True, model)
        logger.info("qna_general_llm_called=true provider=%s model=%s", provider, model)

        persona = self._general_persona_system_prompt()
        try:
            return await self._ai.ask_for_task("summary", question, persona, history or [])
        except Exception:  # noqa: BLE001
            logger.exception("general_llm offline helper failed")
            return None

    def _normalize_question(self, question: str) -> str:
        return re.sub(r"\s+", " ", question.strip().lower())

    def _format_italian_datetime(self, dt: str) -> str:
        try:
            parsed = datetime.fromisoformat(dt)
        except ValueError:
            return dt
        return parsed.astimezone(ROME_TZ).strftime("%Y-%m-%d %H:%M")

    def _decorate_proof_links(self, answer_text: str, evidence: list[dict[str, str]]) -> str:
        if not answer_text:
            return answer_text

        jump_to_label: dict[str, str] = {}
        for item in evidence:
            jump_url = str(item.get("jump_url") or "").strip()
            created_at_iso = str(item.get("created_at_iso") or "").strip()
            if not jump_url:
                continue
            if created_at_iso:
                normalized_iso = created_at_iso.replace("Z", "+00:00")
                try:
                    parsed = datetime.fromisoformat(normalized_iso)
                except ValueError:
                    parsed = None
                if parsed is not None:
                    jump_to_label[jump_url] = parsed.astimezone(ROME_TZ).strftime("🧾 %d/%m %H:%M")

        url_re = r"https://discord\.com/channels/\d+/\d+/\d+"
        decorated = answer_text

        # Step 0: normalize almost-valid markdown links.
        decorated = re.sub(r"\]\s+\(", "](", decorated)
        decorated = re.sub(r"\(\s+", "(", decorated)
        decorated = re.sub(r"\s+\)", ")", decorated)

        def normalize_link_url(match: re.Match[str]) -> str:
            label = match.group(1).strip()
            raw_url = match.group(2)
            cleaned_url = raw_url.replace("\n", "").replace(" ", "")
            return f"[{label}]({cleaned_url})"

        decorated = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", normalize_link_url, decorated)

        def label_for_url(url: str) -> str | None:
            return jump_to_label.get(url)

        # Step 1: transform proof-like labels with parenthesized URL into valid markdown.
        def replace_labeled_proof(match: re.Match[str]) -> str:
            raw_label = re.sub(r"\s+", " ", match.group(1).strip())
            jump_url = match.group(2).strip()
            existing = re.match(r"\[?(🧾\s*\d{1,2}/\d{1,2}\s*\d{1,2}:\d{2})\]?", raw_label)
            if existing:
                label = existing.group(1)
            else:
                label = label_for_url(jump_url) or "🧾 prova"
            if label_for_url(jump_url):
                label = label_for_url(jump_url) or label
            return f"[{label}]({jump_url})"

        decorated = re.sub(
            rf"(\[?🧾\s*\d{{1,2}}/\d{{1,2}}\s*\d{{1,2}}:\d{{2}}\]?)\s*\(\s*({url_re})\s*\)",
            replace_labeled_proof,
            decorated,
        )

        # Normalize any remaining markdown links pointing to discord channels.
        def normalize_or_relabel(match: re.Match[str]) -> str:
            label = match.group(1).strip()
            jump_url = match.group(2).strip()
            mapped = label_for_url(jump_url)
            final_label = mapped or label
            return f"[{final_label}]({jump_url})"

        decorated = re.sub(rf"\[([^\]]+)\]\((({url_re}))\)", normalize_or_relabel, decorated)

        # Step 2: replace proof tokens with naked/parenthesized URLs.
        def replace_proof_with_url(match: re.Match[str]) -> str:
            jump_url = match.group("url").strip()
            label = label_for_url(jump_url)
            if not label:
                return jump_url
            return f"[{label}]({jump_url})"

        decorated = re.sub(
            rf"(?i)(?:\bprov(?:a|e)\.?\b|🧾)\s*[:\-]?\s*\(?\s*(?P<url>{url_re})\s*\)?",
            replace_proof_with_url,
            decorated,
        )

        # Step 2b: naked URLs become timestamped proof links when evidence is available.
        def replace_naked_url(match: re.Match[str]) -> str:
            jump_url = match.group(1)
            label = label_for_url(jump_url)
            if not label:
                return jump_url
            return f"[{label}]({jump_url})"

        decorated = re.sub(rf"(?<!\]\()({url_re})", replace_naked_url, decorated)
        decorated = re.sub(
            r"(?i)\bprov(?:a|e)\.?\s*[:\-]?\s*\((\[[^\]]+\]\(https://discord\.com/channels/\d+/\d+/\d+\))\)",
            r"\1",
            decorated,
        )
        decorated = re.sub(
            r"(?i)\bprov(?:a|e)\.?\s*[:\-]?\s*(\[[^\]]+\]\(https://discord\.com/channels/\d+/\d+/\d+\))",
            r"\1",
            decorated,
        )
        return decorated

    async def _get_qna_daily_limits(self) -> dict[str, int]:
        defaults = {"base": 0, "role1": 1, "role2": 2, "role3": 3, "mod": 999}
        raw = await self._database.get_setting("qna.daily_limits")
        if not raw:
            return defaults
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return defaults
        if not isinstance(parsed, dict):
            return defaults
        limits = defaults.copy()
        for key, value in parsed.items():
            if key not in limits:
                continue
            try:
                limits[key] = int(value)
            except (TypeError, ValueError):
                continue
        return limits

    async def _resolve_qna_limit(
        self,
        interaction: discord.Interaction,
        *,
        profile: str | None = None,
        limits: dict[str, int] | None = None,
    ) -> int:
        profile = profile or await self._entitlements.resolve_profile(interaction.user)
        limits = limits or await self._get_qna_daily_limits()
        tier_limit = int(limits.get(profile, limits.get("base", 0)))
        if interaction.guild_id is None:
            return tier_limit
        bonus, _ = await self._database.get_qna_bonus(str(interaction.guild_id), str(interaction.user.id))
        return tier_limit + max(0, bonus)

    async def _resolve_qna_limit_for_member(self, member, *, profile: str | None = None, limits: dict[str, int] | None = None) -> int:
        profile = profile or await self._entitlements.resolve_profile(member)
        limits = limits or await self._get_qna_daily_limits()
        tier_limit = int(limits.get(profile, limits.get("base", 0)))
        guild = getattr(member, "guild", None)
        if guild is None:
            return tier_limit
        bonus, _ = await self._database.get_qna_bonus(str(guild.id), str(member.id))
        return tier_limit + max(0, bonus)

    def format_for_discord_embed(self, answer_text: str, scope: Literal["general_llm", "channel_qna"]) -> str:
        raw = (answer_text or "").strip()
        if not raw:
            return raw

        if scope == "general_llm":
            if "\n" not in raw and len(raw) > 700:
                sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", raw) if part.strip()]
                if sentences:
                    opening = "💛 **Ci sono!** Ti riassumo al volo in modo chiaro."
                    bullets = [f"• ✨ {sentence}" for sentence in sentences[:5]]
                    closing = "🔎 **Vuoi che lo renda più specifico su un punto preciso?**"
                    return "\n".join([opening, *bullets, closing])
            return raw

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        proof_lines = [line for line in lines if "https://discord.com/channels/" in line or "🧾" in line]
        answer_lines = [line for line in lines if line not in proof_lines]
        sections: list[str] = []
        if answer_lines:
            sections.extend(answer_lines)
        if proof_lines:
            sections.append("\n**Prove**")
            sections.extend(proof_lines)
        return "\n".join(sections) if sections else raw

    def normalize_discord_formatting(self, text: str) -> str:
        normalized = (text or "").strip()
        if not normalized:
            return normalized

        normalized = normalized.replace(" - ", "\n- ")
        normalized = normalized.replace("• ", "\n• ")
        normalized = normalized.replace("👉 ", "\n👉 ")
        normalized = normalized.replace("✨ ", "\n✨ ")
        normalized = re.sub(r"\s-\s\*\*", "\n- **", normalized)

        if "\n" not in normalized and len(normalized) > 500:
            sentences = [part.strip() for part in normalized.split(". ") if part.strip()]
            if sentences:
                normalized = "\n\n".join(sentences)

        return normalized.strip()

    def _get_qna_remote_model_name(self) -> str:
        if self._ai is None:
            return "modello AI"
        return self._ai.get_model_config("summary") or "unknown"

    @staticmethod
    def _strip_leading_answer_label(text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return cleaned
        pattern = re.compile(r"^(?:\*\*)?\s*(?:👇\s*)?risposta\s*:?(?:\*\*)?\s*", re.IGNORECASE)
        while True:
            updated = pattern.sub("", cleaned, count=1).strip()
            if updated == cleaned:
                return cleaned
            cleaned = updated

    def _format_qna_answer_text(
        self,
        question: str,
        answer_text: str,
        evidence: list[dict[str, str]],
        *,
        scope: Literal["general_llm", "channel_qna"],
        mode: Literal["evidence", "plain"],
    ) -> str:
        if mode == "plain":
            base_text = re.sub(r"\s+", " ", (answer_text or "").strip())
        else:
            base_text = self._bulletize_answer(question, answer_text, evidence)
        base_text = self._strip_leading_answer_label(base_text)
        formatted = self.format_for_discord_embed(base_text, scope)
        formatted = self._strip_leading_answer_label(formatted)
        return self.normalize_discord_formatting(formatted)

    def _build_qna_embed(
        self,
        asker_name: str,
        question: str,
        answer_text: str,
        *,
        response_origin: Literal["remote_ai", "local_backend", "error"],
        model_name: str | None = None,
        is_followup: bool = False,
    ) -> discord.Embed:
        cleaned_answer = self._strip_leading_answer_label(answer_text)
        if is_followup:
            description = f"👇 **Risposta:**\n{cleaned_answer}"
        else:
            question_text = (question or "").strip()
            description = (
                f"👋 **{asker_name} chiede:**\n"
                f"{question_text}\n\n"
                f"👇 **Risposta:**\n{cleaned_answer}"
            )
        description = self._truncate_embed_description(description)
        title = "❓ DOMANDA" if response_origin == "error" else "❓ BOTTA & RISPOSTA"
        embed = build_report_cover_embed(
            title=title,
            description=description,
            color=0x9B59B6 if response_origin != "error" else 0xED4245,
            service_name="qna",
        )
        attach_footer_meta(
            embed,
            service_name="qna",
            contributors=[model_name] if response_origin == "remote_ai" and model_name else [],
            used_local_processing=response_origin != "remote_ai",
        )
        return embed

    def _bulletize_answer(self, question: str, answer_text: str, evidence: list[dict[str, str]]) -> str:
        lines = [line.strip() for line in answer_text.splitlines() if line.strip()]
        if not lines:
            return answer_text

        target_raw = self._extract_target_raw(question)
        scoped_evidence = self._filter_evidence_by_target(evidence, target_raw)
        if target_raw and not scoped_evidence:
            logger.info(
                "qna no direct evidence target_raw=%s total_evidence=%s evidence_target=%s produced=%s discarded=%s avg_best_score=%.3f",
                target_raw,
                len(evidence),
                0,
                0,
                0,
                0.0,
            )
            return f"Non risultano messaggi o attività rilevanti per questa richiesta nel periodo indicato."

        final_lines: list[str] = []
        produced = 0
        discarded = 0
        best_scores: list[float] = []
        for raw_line in lines:
            line = re.sub(r"^\s*[•\-–—]\s*", "", raw_line).strip()
            line = self._strip_proof_artifacts(line)
            if not line:
                continue
            proof, score = self._best_evidence_for_bullet(line, scoped_evidence)
            best_scores.append(score)
            if not proof:
                discarded += 1
                continue
            jump_url = str(proof.get("jump_url") or "").strip()
            if not self._is_valid_jump_url(jump_url):
                discarded += 1
                continue
            if not self._is_bullet_relevant(question, line):
                discarded += 1
                continue

            ts = self._format_proof_timestamp(str(proof.get("created_at_iso") or ""))
            if not ts:
                discarded += 1
                continue
            final_lines.append(f"• [🧾 {ts}]({jump_url}) {line}")
            produced += 1

        avg_best_score = (sum(best_scores) / len(best_scores)) if best_scores else 0.0
        logger.info(
            "qna mapping stats target_raw=%s total_evidence=%s evidence_target=%s produced=%s discarded=%s avg_best_score=%.3f",
            target_raw,
            len(evidence),
            len(scoped_evidence),
            produced,
            discarded,
            avg_best_score,
        )
        if final_lines:
            return "\n".join(final_lines)
        if target_raw:
            return f"Non risultano messaggi o attività rilevanti per questa richiesta nel periodo indicato."
        return "Non risultano messaggi o attività rilevanti per questa richiesta nel periodo indicato."

    def _strip_proof_artifacts(self, text: str) -> str:
        cleaned = text or ""
        cleaned = re.sub(r"\[\s*🧾[^\]]*\]\([^)]+\)", "", cleaned)
        cleaned = re.sub(r"🧾\s*\d{1,2}/\d{1,2}\s*\d{1,2}:\d{2}", "", cleaned)
        cleaned = re.sub(r"\(\s*https?://discord\.com/channels/[^)]+\)", "", cleaned)
        cleaned = re.sub(r"https?://discord\.com/channels/\S+", "", cleaned)
        cleaned = re.sub(r"\]\(\s*0\s*\)", "", cleaned)
        cleaned = re.sub(r"\]\(\s*\)", "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
        cleaned = re.sub(r"([,.;:!?]){2,}", r"\1", cleaned)
        return cleaned.strip(" -–—•\t\n\r")

    def _is_valid_jump_url(self, jump_url: str) -> bool:
        return jump_url.startswith("https://discord.com/channels/")

    def _format_proof_timestamp(self, created_at_iso: str) -> str:
        normalized = (created_at_iso or "").strip().replace("Z", "+00:00")
        if not normalized:
            return ""
        try:
            created_at = datetime.fromisoformat(normalized)
        except ValueError:
            return ""
        return created_at.astimezone(ROME_TZ).strftime("%d/%m %H:%M")

    def _score(self, bullet: str, msg: str) -> float:
        bullet_tokens = set(self._norm_tokens(bullet))
        msg_tokens = set(self._norm_tokens(msg))
        if not bullet_tokens or not msg_tokens:
            return 0.0
        return len(bullet_tokens & msg_tokens) / max(len(bullet_tokens), 1)

    def _best_evidence_for_bullet(self, clean_text: str, evidence_pack: list[dict[str, str]]) -> tuple[dict[str, str] | None, float]:
        if not evidence_pack:
            return None, 0.0

        best_item: dict[str, str] | None = None
        best_score = 0.0
        best_content = ""
        for item in evidence_pack:
            jump_url = str(item.get("jump_url") or "").strip()
            if not self._is_valid_jump_url(jump_url):
                continue
            message_content = str(item.get("content") or item.get("snippet") or "")
            score = self._score(clean_text, message_content)
            if score > best_score:
                best_score = score
                best_item = item
                best_content = message_content

        if best_score >= 0.10:
            return best_item, best_score
        logger.info(
            "qna bullet discarded for low evidence overlap score=%.3f bullet='%s' candidate='%s'",
            best_score,
            self._truncate_text(clean_text, 50),
            self._truncate_text(best_content, 50),
        )
        return None, best_score

    def _norm_tokens(self, value: str) -> list[str]:
        base = unicodedata.normalize("NFKD", (value or "").lower())
        base = "".join(char for char in base if unicodedata.category(char) != "Mn")
        base = re.sub(r"[^a-z0-9\s]", " ", base)
        cleaned = re.sub(r"\s+", " ", base).strip()
        return [token for token in cleaned.split() if len(token) >= 2 and token not in IT_STOPWORDS]

    def _clean_target_fragment(self, value: str) -> str:
        cleaned = re.sub(r"<@!?\d+>", " ", value or "")
        cleaned = re.sub(r"[\"'“”‘’`]+", " ", cleaned)
        cleaned = unicodedata.normalize("NFKD", cleaned)
        cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch) != "Mn")
        cleaned = re.sub(r"[^\w\s]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned[:40]

    def _extract_target_raw(self, question: str) -> str | None:
        q = (question or "").strip()
        if not q:
            return None

        patterns: list[tuple[str, int]] = [
            (r"\bcosa\s+ha\s+detto\s+(.+?)(?:\?|$)", 1),
            (r"\b(è|è)\s+vero\s+che\s+(.+?)\s+ha\s+detto\b", 2),
            (r"\b(.+?)\s+ha\s+detto\b", 1),
        ]
        for pattern, group in patterns:
            match = re.search(pattern, q, flags=re.IGNORECASE)
            if not match:
                continue
            candidate = self._clean_target_fragment(match.group(group))
            if candidate:
                return candidate
        return None

    def _author_matches_target(self, author_name: str, target_raw: str) -> bool:
        author_tokens = set(self._norm_tokens(author_name))
        target_tokens = self._norm_tokens(target_raw)
        if not target_tokens:
            return False
        if len(target_tokens) >= 2:
            hits = sum(1 for token in target_tokens if token in author_tokens)
            return hits >= len(target_tokens)
        target = target_tokens[0]
        return target in author_tokens or any(token.startswith(target) or target.startswith(token) for token in author_tokens)

    def _extract_target_speaker(self, question: str) -> str | None:
        return self._extract_target_raw(question)

    def _filter_evidence_by_target(self, evidence: list[dict[str, str]], target_raw: str | None) -> list[dict[str, str]]:
        if not target_raw:
            return evidence
        filtered: list[dict[str, str]] = []
        for item in evidence:
            if self._author_matches_target(str(item.get("author_name") or ""), target_raw):
                filtered.append(item)
        return filtered

    def _normalize_text(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKD", (text or "").lower())
        normalized = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _tokenize(self, text: str) -> set[str]:
        normalized = self._normalize_text(text)
        return {token for token in normalized.split() if len(token) > 1 and token not in IT_STOPWORDS}

    def _is_bullet_relevant(self, question: str, bullet: str) -> bool:
        q_raw = (question or "").strip()
        b_raw = (bullet or "").strip()
        if not q_raw or not b_raw:
            return False

        q_norm = re.sub(r"[^\w\s]", " ", q_raw.lower())
        b_norm = re.sub(r"[^\w\s]", " ", b_raw.lower())
        stopwords = {
            "come", "quando", "dove", "cosa", "perche", "perché", "quale", "quali", "della", "delle", "degli", "dello",
            "dell", "questa", "questo", "quello", "quella", "nella", "nelle", "negli", "nello", "dopo", "prima", "sulla",
            "sulle", "solo", "sono", "anche", "dalla", "dalle", "dallo", "dentro", "fuori", "avete", "abbiamo", "hanno",
            "dicono", "detto", "fatto", "oggi", "ieri", "domani", "delle", "degli", "dati", "messaggi", "canale",
        }

        proper_names = [token.lower() for token in re.findall(r"\b[A-ZÀ-Ý][\wÀ-ÿ']+\b", q_raw)]
        long_tokens = [
            token
            for token in re.findall(r"\b\w{4,}\b", q_norm)
            if token not in stopwords
        ]
        keywords = set(proper_names + long_tokens)
        if keywords and any(keyword in b_norm for keyword in keywords):
            return True

        asks_what_said = bool(re.search(r"\bcosa\s+ha\s+detto\b|\bha\s+detto\b", q_norm))
        speech_tokens = ["ha detto", "ha promesso", "ha confermato", "ha scritto", "ha risposto"]
        if asks_what_said and any(token in b_norm for token in speech_tokens):
            return True
        return False

    def _truncate_embed_description(self, description: str, *, max_len: int = 4096) -> str:
        if len(description) <= max_len:
            return description
        return description[: max_len - 1].rstrip() + "…"

    async def _build_qna_payload(
        self,
        guild_id: str,
        channel_id: str,
        question: str,
        *,
        source: discord.Interaction | discord.Message | None = None,
        session_user_id: str = "",
    ) -> dict[str, object]:
        guild = source.guild if source else None
        targets, ambiguous_note, capped_note = self._infer_target_members_with_notes(source, question, guild)
        start_dt, end_dt, range_label = self.infer_time_range(question, person_focused=bool(targets))
        breadth = self.classify_qna_breadth(question)
        budgets = self._qna_budgets_for_breadth(breadth)
        explicit_time = self._has_explicit_time_marker(question)

        if breadth == "broad" and not explicit_time and "senza limiti" not in question.lower():
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(hours=24)
            range_label = "ultime 24 ore"

        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()
        session_turns = int(budgets.get("session_turns") or 1)
        conversation_history = await self._load_qna_history(guild_id, channel_id, session_user_id, max_turns=session_turns)
        session_signature = self._session_signature(conversation_history)

        retrieval_mode = "full_history"
        if explicit_time:
            retrieval_mode = "window"

        evidence_max = int(budgets.get("evidence_max") or 20)
        snippet_max = int(budgets.get("snippet_max") or 140)
        candidate_pool = int(budgets.get("candidate_pool") or 180)

        window_rows = await self._database.fetch_messages_in_range_time_bucketed(
            channel_id=channel_id,
            start_ts=start_iso,
            end_ts=end_iso,
            buckets=10,
            per_bucket_limit=max(6, evidence_max),
            include_bots=False,
        )
        window_ranked = self._rank_evidence_rows(window_rows, question)

        full_history_needed = False
        if explicit_time:
            evidence_ranked = window_ranked[:evidence_max]
            if len(evidence_ranked) < 6 or self._is_weak_relevance(evidence_ranked):
                full_history_needed = True
                retrieval_mode = "window_then_full"
        else:
            if breadth == "broad":
                evidence_ranked = window_ranked[:evidence_max]
                if len(evidence_ranked) < 6 or self._is_weak_relevance(evidence_ranked):
                    full_history_needed = True
                    retrieval_mode = "window_then_full"
            else:
                full_history_needed = True
                retrieval_mode = "full_history"
                evidence_ranked = []

        if full_history_needed:
            min_content_length = 16 if breadth == "broad" else 0
            full_rows = await self._database.search_channel_messages(
                channel_id=channel_id,
                query_text=question,
                limit=evidence_max,
                candidate_pool=candidate_pool,
                min_content_length=min_content_length,
            )
            evidence_ranked = self._normalize_search_rows(full_rows)

        evidence_pack = self._build_evidence_pack(evidence_ranked, guild, snippet_max=snippet_max, evidence_max=evidence_max)
        logger.info(
            "qna retrieval mode=%s channel_id=%s breadth=%s evidence_count=%s",
            retrieval_mode,
            channel_id,
            breadth,
            len(evidence_pack),
        )

        context: dict[str, object] = {
            "time_range_label": range_label,
            "start": start_iso,
            "end": end_iso,
            "retrieval_mode": retrieval_mode,
            "conversation_previous": conversation_history,
            "evidence": evidence_pack,
            "breadth": breadth,
        }
        constraints = [
            "solo canale corrente",
            "non includere PII",
            "rispondi in italiano",
            "usa solo le prove fornite",
            "non inventare contenuti",
            "rispondi solo alla domanda senza contesto generale extra",
            "massimo 4 bullet verificabili",
            "rispondi SOLO con affermazioni ricavate dai messaggi evidenza del target quando presente",
            "se non ci sono prove dirette dillo chiaramente",
        ]
        cache_ttl = int(budgets.get("cache_ttl") or 45 * 60)
        empty_reply = ""
        if not evidence_pack and not targets:
            empty_reply = "Non risultano messaggi o attività rilevanti per questa richiesta nel periodo indicato."

        if targets:
            per_target_messages: dict[str, list[dict[str, str]]] = {}
            target_rows_for_payload: list[dict[str, str]] = []
            missing_targets: list[str] = []
            for target in targets:
                target_rows = await self._database.fetchall(
                    """
                    SELECT m.ts, m.content, m.message_id, m.guild_id, m.channel_id
                    FROM messages AS m
                    LEFT JOIN users AS u ON u.user_id = m.author_id
                    WHERE m.channel_id = ?
                      AND m.author_id = ?
                      AND m.ts >= ?
                      AND m.ts <= ?
                      AND COALESCE(m.is_deleted, 0) = 0
                      AND COALESCE(u.is_bot, 0) = 0
                    ORDER BY m.ts ASC
                    LIMIT 120
                    """,
                    (channel_id, str(target.id), start_iso, end_iso),
                )
                sampled_rows = self._sample_messages(list(target_rows), keep_start=12, keep_end=40)
                items: list[dict[str, str]] = []
                for row in sampled_rows:
                    content = self._truncate_text(str(row["content"] or ""), 220).strip()
                    if not content:
                        continue
                    message_id = str(row["message_id"] or "").strip()
                    row_guild_id = str(row["guild_id"] or guild_id)
                    row_channel_id = str(row["channel_id"] or channel_id)
                    jump_url = f"https://discord.com/channels/{row_guild_id}/{row_channel_id}/{message_id}" if message_id else ""
                    items.append(
                        {
                            "created_at": str(row["ts"] or ""),
                            "content": content,
                            "message_id": message_id,
                            "channel_id": row_channel_id,
                            "guild_id": row_guild_id,
                            "jump_url": jump_url,
                        }
                    )
                per_target_messages[str(target.id)] = items
                target_rows_for_payload.append({"id": str(target.id), "display_name": target.display_name})
                if not items:
                    missing_targets.append(target.display_name)

            if len(missing_targets) == len(targets):
                names = ", ".join(missing_targets)
                empty_reply = (
                    f"Non ho trovato messaggi di {names} nel periodo richiesto ({range_label}). "
                    "Prova con una finestra più ampia, ad esempio 'ultimi 7 giorni'."
                )
            context.update(
                {
                    "targets": target_rows_for_payload,
                    "per_target_messages": per_target_messages,
                    "focus_instruction": (
                        "Per ciascun target: massimo 4 bullet strettamente pertinenti alla domanda, frasi verificabili e niente contesto generale. "
                        "Rispondi SOLO con affermazioni ricavate dai messaggi evidenza del target. "
                        "Se mancano prove dirette, dichiaralo esplicitamente e non inventare."
                    ),
                }
            )

        if breadth == "broad":
            context["focus_instruction"] = (
                "Risposta sintetica (max 4 bullet) solo su elementi pertinenti alla domanda, senza contesto generale extra. "
                "Se non ci sono prove dirette, dichiaralo chiaramente e non inventare."
            )
        elif "focus_instruction" not in context:
            context["focus_instruction"] = (
                "Rispondi solo alla domanda usando prove fornite, massimo 4 bullet verificabili e nessun contesto generale. "
                "Se non ci sono prove dirette, dillo chiaramente senza inventare. Se la domanda è follow-up, usa la conversazione precedente."
            )

        prompt_obj = {
            "system": (
                "Sei il servizio QnA del Barcellometro. Rispondi solo usando le prove fornite. "
                "Non inventare contenuti. Se c'è un target speaker, usa solo evidenze del target. "
                "Se la domanda è un follow-up, usa la conversazione precedente."
            ),
            "question": question,
            "constraints": constraints,
            "context": context,
            "output_schema": {"can_answer": "bool", "answer": "string", "refusal_reason": "string|null"},
        }

        target_ids = sorted(str(member.id) for member in targets)
        target_ids_fragment = "-".join(target_ids) if target_ids else "all"
        cache_fragment = f"{channel_id}:{retrieval_mode}:{start_iso}:{end_iso}:{breadth}"
        merged_note = "\n".join(note for note in [ambiguous_note, capped_note] if note).strip()
        return {
            "payload": json.dumps(prompt_obj, ensure_ascii=False),
            "cache_fragment": cache_fragment,
            "target_ids_fragment": target_ids_fragment,
            "cache_ttl": cache_ttl,
            "empty_reply": empty_reply,
            "ambiguous_note": merged_note,
            "session_user_id": session_user_id,
            "session_signature": session_signature,
            "breadth": breadth,
            "evidence_pack": evidence_pack,
        }

    def infer_time_range(
        self,
        question: str,
        tz: str = "Europe/Rome",
        *,
        person_focused: bool = False,
    ) -> tuple[datetime, datetime, str]:
        local_tz = ZoneInfo(tz)
        q = question.lower()
        now_local = datetime.now(local_tz)
        now_utc = datetime.now(timezone.utc)

        def as_utc(dt_local: datetime) -> datetime:
            return dt_local.astimezone(timezone.utc)

        def finalize(start: datetime, end: datetime, label: str) -> tuple[datetime, datetime, str]:
            logger.info(
                "qna time_range label=%s start=%s end=%s",
                label,
                start.isoformat(),
                end.isoformat(),
            )
            return start, end, label

        today_start = datetime.combine(now_local.date(), datetime.min.time(), tzinfo=local_tz)
        if "ultima ora" in q or "ultim'ora" in q:
            return finalize(now_utc - timedelta(hours=1), now_utc, "ultima ora")
        if (m := re.search(r"ultime\s+(\d{1,2})\s+ore", q)):
            hours = max(1, int(m.group(1)))
            return finalize(now_utc - timedelta(hours=hours), now_utc, f"ultime {hours} ore")
        if (m := re.search(r"\b(\d{1,2})\s+ore\s+fa\b", q)):
            hours = max(1, int(m.group(1)))
            return finalize(now_utc - timedelta(hours=hours), now_utc, f"{hours} ore fa")
        if (m := re.search(r"ultimi\s+(\d{1,2})\s+giorni", q)):
            days = min(30, max(1, int(m.group(1))))
            return finalize(now_utc - timedelta(days=days), now_utc, f"ultimi {days} giorni")
        if "l'altro ieri" in q or "l’altro ieri" in q:
            day_start = today_start - timedelta(days=2)
            return finalize(as_utc(day_start), as_utc(day_start + timedelta(days=1)), "l'altro ieri")
        if (m := re.search(r"\b(\d{1,2})\s+giorni?\s+fa\b", q)):
            days = min(30, max(1, int(m.group(1))))
            day_start = today_start - timedelta(days=days)
            day_end = day_start + timedelta(days=1)
            suffix = "giorno" if days == 1 else "giorni"
            return finalize(as_utc(day_start), as_utc(day_end), f"{days} {suffix} fa")
        if "scorsa settimana" in q:
            week_start = today_start - timedelta(days=today_start.weekday(), weeks=1)
            return finalize(as_utc(week_start), as_utc(week_start + timedelta(days=7)), "scorsa settimana")
        if (m := re.search(r"\b(\d{1,2})\s+settimane?\s+fa\b", q)):
            weeks = max(1, int(m.group(1)))
            reference_day = today_start - timedelta(weeks=weeks)
            week_start = reference_day - timedelta(days=reference_day.weekday())
            suffix = "settimana" if weeks == 1 else "settimane"
            return finalize(as_utc(week_start), as_utc(week_start + timedelta(days=7)), f"{weeks} {suffix} fa")
        if "mese scorso" in q:
            month_start = today_start.replace(day=1)
            previous_month_end = month_start - timedelta(days=1)
            previous_month_start = month_start.replace(year=previous_month_end.year, month=previous_month_end.month)
            return finalize(as_utc(previous_month_start), as_utc(month_start), "mese scorso")
        if "stamattina" in q:
            morning = today_start + timedelta(hours=6)
            return finalize(as_utc(morning), now_utc, "stamattina")
        if "questa sera" in q:
            evening = today_start + timedelta(hours=18)
            return finalize(as_utc(evening), now_utc, "questa sera")
        if "ieri" in q:
            yesterday_start = today_start - timedelta(days=1)
            return finalize(as_utc(yesterday_start), as_utc(today_start), "ieri")
        if "oggi" in q:
            return finalize(as_utc(today_start), now_utc, "oggi")
        if "questa settimana" in q:
            week_start = today_start - timedelta(days=today_start.weekday())
            return finalize(as_utc(week_start), now_utc, "questa settimana")
        default_hours = 24 if person_focused else 6
        return finalize(now_utc - timedelta(hours=default_hours), now_utc, f"ultime {default_hours} ore")

    def infer_target_members(
        self,
        interaction_or_message: discord.Interaction | discord.Message | None,
        question: str,
        guild: discord.Guild | None,
    ) -> list[discord.Member]:
        targets, _, _ = self._infer_target_members_with_notes(interaction_or_message, question, guild)
        return targets

    def _infer_target_members_with_notes(
        self,
        interaction_or_message: discord.Interaction | discord.Message | None,
        question: str,
        guild: discord.Guild | None,
    ) -> tuple[list[discord.Member], str, str]:
        if guild is None:
            return [], "", ""

        targets: list[discord.Member] = []
        ambiguous_note = ""
        capped_note = ""

        mention_ids = re.findall(r"<@!?(\d+)>", question)
        for mention_id in mention_ids:
            member = guild.get_member(int(mention_id))
            if member and not member.bot:
                targets.append(member)

        if isinstance(interaction_or_message, discord.Message):
            for member in interaction_or_message.mentions:
                if not member.bot:
                    targets.append(member)

        if isinstance(interaction_or_message, discord.Interaction):
            data = interaction_or_message.data if isinstance(interaction_or_message.data, dict) else {}
            resolved = data.get("resolved") if isinstance(data, dict) else None
            users = resolved.get("users") if isinstance(resolved, dict) else None
            if isinstance(users, dict):
                for user_id in users.keys():
                    member = guild.get_member(int(user_id))
                    if member and not member.bot:
                        targets.append(member)

        if not targets:
            raw_tokens = [token.strip() for token in re.split(r"\s*(?:,|\be\b|&|\band\b)\s*", question, flags=re.IGNORECASE)]
            stopwords = {
                "che", "cosa", "oggi", "ieri", "interessante", "ha", "scritto", "nel", "canale", "questa", "settimana",
                "ultima", "ultime", "ultimi", "ora", "ore", "giorni", "stamattina", "sera", "chi", "di"
            }
            name_tokens: list[str] = []
            for token in raw_tokens:
                words = [w for w in re.findall(r"\b[\wÀ-ÿ']+\b", token) if len(w) > 2]
                for w in words:
                    if w.lower() in stopwords:
                        continue
                    if w[0].isupper() or len(raw_tokens) > 1:
                        name_tokens.append(w)

            unresolved_count = 0
            for token in name_tokens:
                token_l = token.lower()
                prefix_matches = [
                    m for m in guild.members
                    if not m.bot and (m.display_name.lower().startswith(token_l) or m.name.lower().startswith(token_l))
                ]
                if len(prefix_matches) == 1:
                    targets.append(prefix_matches[0])
                    continue
                if len(prefix_matches) > 1:
                    unresolved_count += 1
                    continue

                choices: dict[str, discord.Member] = {}
                for member in guild.members:
                    if member.bot:
                        continue
                    choices[member.display_name.lower()] = member
                    choices[member.name.lower()] = member
                close = difflib.get_close_matches(token_l, list(choices.keys()), n=2, cutoff=0.9)
                if len(close) == 1:
                    targets.append(choices[close[0]])
                elif len(close) > 1:
                    unresolved_count += 1

            if unresolved_count > 0 and not targets:
                ambiguous_note = "Non sono sicuro di chi intendi. Intanto rispondo sul canale."

        deduped: list[discord.Member] = []
        seen_ids: set[int] = set()
        for member in targets:
            if member.id in seen_ids:
                continue
            seen_ids.add(member.id)
            deduped.append(member)

        if len(deduped) > 3:
            capped = len(deduped)
            deduped = deduped[:3]
            capped_note = f"Ho considerato i primi 3 target su {capped} richiesti."

        return deduped, ambiguous_note, capped_note

    def _truncate_text(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return f"{text[: max_chars - 1]}…"

    def _sample_messages(self, rows: list[object], *, keep_start: int, keep_end: int) -> list[object]:
        if len(rows) <= keep_start + keep_end:
            return rows
        return rows[:keep_start] + rows[-keep_end:]

    def _has_explicit_time_marker(self, question: str) -> bool:
        q = question.lower()
        if re.search(r"\b\d{1,2}\s+(?:ore|giorni?|settimane?)\s+fa\b", q):
            return True
        return any(
            token in q for token in [
                "oggi",
                "ieri",
                "l'altro ieri",
                "l’altro ieri",
                "stamattina",
                "questa settimana",
                "scorsa settimana",
                "questa sera",
                "ultima ora",
                "ultim'ora",
                "ultime",
                "ultimi",
                "ore fa",
                "giorni fa",
                "settimane fa",
                "mese",
                "mese scorso",
            ]
        )

    def _rank_evidence_rows(self, rows: list[object], question: str) -> list[dict[str, object]]:
        keywords = [token for token in re.findall(r"\w+", question.lower()) if len(token) > 2][:12]
        phrase = question.strip().lower()
        ranked: list[dict[str, object]] = []
        for row in rows:
            content = str(row["content"] or "")
            lower = content.lower()
            score = 0
            for kw in keywords:
                idx = lower.find(kw)
                if idx >= 0:
                    score += 1
                    if idx < 80:
                        score += 1
            if phrase and phrase in lower:
                score += 2
            if score <= 0 and keywords:
                continue
            ranked.append(
                {
                    "message_id": str(row["message_id"] or ""),
                    "guild_id": str(row["guild_id"] or ""),
                    "channel_id": str(row["channel_id"] or ""),
                    "author_id": str(row["author_id"] or ""),
                    "author_name": str(row["author_name"] or row["author_id"] or ""),
                    "created_at": str(row["ts"] or row["created_at"] or ""),
                    "content": content,
                    "score": score,
                }
            )
        ranked.sort(key=lambda item: (int(item.get("score", 0)), str(item.get("created_at", ""))), reverse=True)
        return ranked

    def _normalize_search_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        ranked: list[dict[str, object]] = []
        for row in rows:
            ranked.append(
                {
                    "message_id": str(row.get("message_id") or ""),
                    "guild_id": str(row.get("guild_id") or ""),
                    "channel_id": str(row.get("channel_id") or ""),
                    "author_id": str(row.get("author_id") or ""),
                    "author_name": str(row.get("author_name") or row.get("author_id") or ""),
                    "created_at": str(row.get("created_at") or ""),
                    "content": str(row.get("content") or ""),
                    "score": int(row.get("score") or 0),
                }
            )
        return ranked

    def _is_weak_relevance(self, ranked_rows: list[dict[str, object]]) -> bool:
        if not ranked_rows:
            return True
        top_scores = [int(r.get("score") or 0) for r in ranked_rows[:8]]
        avg = sum(top_scores) / max(1, len(top_scores))
        return avg < 2

    def _build_evidence_pack(
        self,
        ranked_rows: list[dict[str, object]],
        guild: discord.Guild | None,
        *,
        snippet_max: int,
        evidence_max: int,
    ) -> list[dict[str, str]]:
        pack: list[dict[str, str]] = []
        for row in ranked_rows[: max(1, min(60, evidence_max))]:
            guild_id = str(row.get("guild_id") or "")
            channel_id = str(row.get("channel_id") or "")
            message_id = str(row.get("message_id") or "")
            jump_url = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}" if message_id else ""
            author_id = str(row.get("author_id") or "")
            author_name = str(row.get("author_name") or author_id)
            if guild and author_id.isdigit() and author_name == author_id:
                member = guild.get_member(int(author_id))
                if member is not None:
                    author_name = member.display_name
            content = str(row.get("content") or "")
            pack.append(
                {
                    "message_id": message_id,
                    "channel_id": channel_id,
                    "author_id": author_id,
                    "author_name": author_name,
                    "created_at": str(row.get("created_at") or ""),
                    "created_at_iso": str(row.get("created_at") or ""),
                    "content": content,
                    "snippet": self._truncate_text(content, max(80, snippet_max)),
                    "jump_url": jump_url,
                }
            )
        return pack

    async def _load_qna_history(self, guild_id: str, channel_id: str, user_id: str, *, max_turns: int = 2) -> list[dict[str, str]]:
        if not user_id:
            return []
        now_iso = datetime.now(timezone.utc).isoformat()
        history = await self._database.get_qna_session_history(guild_id, channel_id, user_id, now_iso)
        if max_turns <= 0:
            return []
        normalized: list[dict[str, str]] = []
        for entry in history[-max_turns:]:
            q = self._truncate_text(str(entry.get("q") or ""), 300)
            a = self._truncate_text(str(entry.get("a") or ""), 400)
            ts = str(entry.get("ts") or "")
            if q:
                normalized.append({"q": q, "a": a, "ts": ts})
        return normalized

    async def _store_qna_turn(self, guild_id: str, channel_id: str, user_id: str, question: str, answer: str) -> None:
        if not user_id:
            return
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        history = await self._database.get_qna_session_history(guild_id, channel_id, user_id, now_iso)
        history.append({"q": self._truncate_text(question, 300), "a": self._truncate_text(answer, 400), "ts": now_iso})
        history = history[-4:]
        expires_at = (now + timedelta(minutes=30)).isoformat()
        await self._database.upsert_qna_session_history(guild_id, channel_id, user_id, history, now_iso, expires_at)

    def _session_signature(self, history: list[dict[str, str]]) -> str:
        if not history:
            return "nosession"
        raw = "|".join(str(item.get("q") or "") for item in history[-2:])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def classify_qna_breadth(self, question: str) -> str:
        q = question.strip().lower()
        if not q:
            return "normal"
        broad_tokens = [
            "riassumi",
            "cosa è successo",
            "che hanno detto",
            "di cosa si parla",
            "tutto",
            "in generale",
            "spiega",
            "dammi un recap",
            "recap",
        ]
        narrow_signals = 0
        if re.search(r"<@!?\d+>", question):
            narrow_signals += 1
        if self._has_explicit_time_marker(question):
            narrow_signals += 1
        if re.search(r"\b\w+\s+\d{4}\b", question):
            narrow_signals += 1
        if len([t for t in re.findall(r"\w+", q) if len(t) > 3]) >= 4:
            narrow_signals += 1
        broad_signals = sum(1 for token in broad_tokens if token in q)
        if len(q) < 18 and "?" in q:
            broad_signals += 1
        if broad_signals >= 1 and narrow_signals == 0:
            return "broad"
        if narrow_signals >= 2:
            return "narrow"
        return "normal"

    def _qna_budgets_for_breadth(self, breadth: str) -> dict[str, int]:
        if breadth == "narrow":
            return {
                "candidate_pool": 220,
                "evidence_max": 30,
                "snippet_max": 180,
                "session_turns": 2,
                "cache_ttl": 30 * 60,
            }
        if breadth == "broad":
            return {
                "candidate_pool": 120,
                "evidence_max": 12,
                "snippet_max": 120,
                "session_turns": 1,
                "cache_ttl": 60 * 60,
            }
        return {
            "candidate_pool": 180,
            "evidence_max": 22,
            "snippet_max": 150,
            "session_turns": 2,
            "cache_ttl": 45 * 60,
        }

    def _shrink_payload_for_budget(self, payload_obj: dict[str, object], breadth: str) -> dict[str, object]:
        obj = json.loads(json.dumps(payload_obj, ensure_ascii=False))
        target_tokens = 8000 if breadth == "broad" else 12000
        steps: list[str] = []

        def approx_tokens() -> int:
            return len(json.dumps(obj, ensure_ascii=False)) // 4

        def trim_evidence(max_items: int) -> None:
            context = obj.get("context")
            if isinstance(context, dict) and isinstance(context.get("evidence"), list):
                context["evidence"] = context["evidence"][:max_items]

        def trim_snippets(max_chars: int) -> None:
            context = obj.get("context")
            if isinstance(context, dict) and isinstance(context.get("evidence"), list):
                for item in context["evidence"]:
                    if isinstance(item, dict) and "snippet" in item:
                        item["snippet"] = self._truncate_text(str(item.get("snippet") or ""), max_chars)

        original_tokens = approx_tokens()
        for size in [20, 12, 8]:
            if approx_tokens() <= target_tokens:
                break
            trim_evidence(size)
            steps.append(f"evidence->{size}")
        for chars in [120, 80]:
            if approx_tokens() <= target_tokens:
                break
            trim_snippets(chars)
            steps.append(f"snippet->{chars}")
        if approx_tokens() > target_tokens:
            context = obj.get("context")
            if isinstance(context, dict):
                context.pop("channel_context", None)
                context.pop("recent_messages", None)
                steps.append("drop_optional_context")
        if approx_tokens() > target_tokens:
            context = obj.get("context")
            if isinstance(context, dict) and isinstance(context.get("conversation_previous"), list):
                context["conversation_previous"] = context["conversation_previous"][:1]
                steps.append("session->1")
        if approx_tokens() > target_tokens:
            trim_evidence(6)
            steps.append("evidence->6")

        logger.info(
            "qna payload shrink breadth=%s tokens_before=%s tokens_after=%s steps=%s",
            breadth,
            original_tokens,
            approx_tokens(),
            steps,
        )
        return obj

    async def _ask_ai_json(self, payload: str) -> dict[str, object] | None:
        if self._ai is None or not self._ai.is_enabled() or self._ai.client() is None:
            return None
        text = await self._ai.ask_for_task("summary", payload, "Rispondi SOLO con JSON valido, senza markdown e senza testo aggiuntivo.")
        text = text or ""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None


def is_out_of_scope_question(question: str) -> bool:
    q = question.lower()
    needles = ["altro canale", "privato", "salottino", "dm", "sezione privata", "cosa dicono in"]
    return any(n in q for n in needles)


def is_sensitive_question(question: str) -> bool:
    q = question.lower()
    needles = ["numero", "telefono", "indirizzo", "email", "contatto", "iban", "carta", "codice fiscale", "documento"]
    return any(n in q for n in needles)
