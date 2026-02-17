from __future__ import annotations

import asyncio
import difflib
import json
import logging
import hashlib
import random
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

import discord

from app.services.barcello import BarcelloService
from app.services.community_insights import CommunityInsightsService
from app.services.config_file_loader import load_json_file
from app.services.database import DatabaseService
from app.services.entitlements import EntitlementsService
from app.services.ingest import EventEnvelope
from app.utils.pii import contains_pii

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")
PHRASE_FALLBACK_TEMPLATES = {
    "DEFAULT": "Questa frase è riapparsa! Ultima volta: {last_seen_human} fa ({last_seen_dt}). È la tua {count_user}ª volta.",
    "FIRST": "Frase rilevata per la prima volta in questo trigger. È la tua {count_user}ª volta.",
}
PHRASE_PLACEHOLDERS = {
    "{author}",
    "{author_name}",
    "{phrase}",
    "{count_user}",
    "{last_seen_human}",
    "{last_seen_dt}",
}
BARCELLO_TRIGGER_CONFIG_PATH = "settings/barcello_trigger.json"
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
        self._bot: discord.Client | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self, bot: discord.Client) -> None:
        self._bot = bot
        if self._task is None:
            self._task = asyncio.create_task(self._barcello_loop())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def on_event(self, envelope: EventEnvelope) -> None:
        if envelope.event_type != "message.create":
            return
        if not envelope.guild_id or not envelope.channel_id or not envelope.content:
            return
        await self._handle_phrases(envelope)

    async def _qna_reply(self, interaction: discord.Interaction, text: str, *, ephemeral: bool) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=ephemeral)
            return
        await interaction.response.send_message(text, ephemeral=ephemeral)

    async def handle_qna_question(self, interaction: discord.Interaction, question: str) -> None:
        question_text = (question or "").strip()
        if interaction.guild_id is None or interaction.channel_id is None:
            await self._qna_reply(interaction, "Usa questo comando in un canale.", ephemeral=True)
            return
        if not question_text:
            await self._qna_reply(interaction, "Inserisci una domanda valida.", ephemeral=True)
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=False, thinking=True)

        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        if not await self._database.get_trigger_enabled(guild_id, channel_id, "qna"):
            await self._qna_reply(interaction, "Il trigger Q&A non è abilitato in questo canale.", ephemeral=True)
            return
        if is_out_of_scope_question(question_text):
            await self._qna_reply(interaction, "Posso rispondere solo su questo canale.", ephemeral=True)
            return
        if is_sensitive_question(question_text):
            await self._qna_reply(interaction, "Non posso aiutare con dati personali o sensibili.", ephemeral=True)
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
            await self._qna_reply(interaction, upgrade_text, ephemeral=True)
            return

        limit = await self._resolve_qna_limit(interaction, profile=profile, limits=limits)
        window_date = datetime.now(ROME_TZ).date().isoformat()
        used = await self._database.get_usage(guild_id, str(interaction.user.id), "qna", window_date)
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
            await self._qna_reply(interaction, message, ephemeral=True)
            return

        question_clean = question_text
        if not question_clean.endswith("?"):
            question_clean = f"{question_clean}?"
        public_content = f"{interaction.user.mention} **chiede:** {question_clean}"

        scope = await self._decide_qna_scope(question_clean)
        answer = await self._handle_qna(
            scope=scope,
            guild_id=guild_id,
            channel_id=channel_id,
            question=question_clean,
            source=interaction,
        )
        if answer is None:
            await self._qna_reply(interaction, "AI non disponibile al momento.", ephemeral=True)
            return
        if not answer.get("can_answer"):
            await self._qna_reply(interaction, str(answer.get("refusal_reason") or "Non posso rispondere."), ephemeral=True)
            return
        text = str(answer.get("answer") or "").strip()
        if not text:
            await self._qna_reply(interaction, "Risposta non valida.", ephemeral=True)
            return

        evidence_pack = answer.get("evidence_pack") if isinstance(answer, dict) else []
        if not isinstance(evidence_pack, list):
            evidence_pack = []

        if contains_pii(text):
            await self._qna_reply(interaction, "Non posso condividere dati personali.", ephemeral=True)
            return

        embed = self._build_qna_embed(question_clean, text, evidence_pack)

        await self._database.increment_usage(
            guild_id,
            str(interaction.user.id),
            "qna",
            window_date,
            datetime.now(timezone.utc).isoformat(),
        )
        await interaction.followup.send(content=public_content, embed=embed, ephemeral=False)

    async def handle_message_qna(self, message: discord.Message) -> None:
        try:
            if message.guild is None:
                return
            content = (message.content or "").strip()
            if not content:
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
                await message.reply("Per fare domande usa /ask e fai upgrade a PLUS/PRO/PRO MAX.", mention_author=False)
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
            answer = await self._handle_qna(
                scope=scope,
                guild_id=guild_id,
                channel_id=channel_id,
                question=question_clean,
                source=message,
            )
            if answer is None or not answer.get("can_answer"):
                await message.reply((answer or {}).get("refusal_reason") or "Non posso rispondere.", mention_author=False)
                return

            text = str(answer.get("answer") or "").strip()
            if not text:
                await message.reply("Risposta non valida.", mention_author=False)
                return

            evidence_pack = answer.get("evidence_pack") if isinstance(answer, dict) else []
            if not isinstance(evidence_pack, list):
                evidence_pack = []

            if contains_pii(text):
                await message.reply("Non posso condividere dati personali.", mention_author=False)
                return

            await self._database.increment_usage(guild_id, str(message.author.id), "qna", window_date, datetime.now(timezone.utc).isoformat())
            embed = self._build_qna_embed(question_clean, text, evidence_pack)
            await message.reply(
                content=f"{message.author.mention} **chiede:** {question_clean}",
                embed=embed,
                mention_author=False,
            )
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

    async def _barcello_loop(self) -> None:
        while True:
            try:
                await self._poll_barcello()
                await self._poll_insights()
            except Exception:  # noqa: BLE001
                logger.exception("Trigger barcello poll failed")
            await asyncio.sleep(60)

    async def _poll_barcello(self) -> None:
        if self._bot is None:
            return
        config = load_json_file(BARCELLO_TRIGGER_CONFIG_PATH)
        window_minutes = config.get("window_minutes")
        if not isinstance(window_minutes, int) or window_minutes <= 0:
            window_minutes = 60
        min_messages = config.get("min_messages")
        if not isinstance(min_messages, int) or min_messages <= 0:
            min_messages = 10
        rows = await self._database.list_enabled_trigger_channels("barcello")
        for row in rows:
            guild_id = str(row["guild_id"])
            channel_id = str(row["channel_id"])
            window_end = datetime.now(timezone.utc)
            window_start = window_end - timedelta(minutes=window_minutes)
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
            if message_count < min_messages:
                logger.debug(
                    "barcello skip low activity",
                    extra={"channel_id": channel_id, "count": message_count, "min_messages": min_messages},
                )
                continue
            status = await self._barcello.get_current_status(guild_id, channel_id=channel_id, window_minutes=window_minutes)
            color = self._normalize_barcello_color(status.get("color"))
            raw_color = color or ""
            score = int(status.get("score") or 0)
            prev = await self._database.get_barcello_trigger_state(guild_id, channel_id)
            prev_color = self._normalize_barcello_color(prev.get("last_color") if prev else None)
            prev_score = int(prev.get("last_score")) if prev and prev.get("last_score") is not None else None
            stable_color = self._apply_hysteresis(prev_color, raw_color, score)
            now = datetime.now(timezone.utc)
            now_iso = now.isoformat()

            if prev_color is not None and stable_color == prev_color:
                await self._database.upsert_barcello_trigger_state(guild_id, channel_id, stable_color, score, now_iso)
                continue

            if prev_score is not None and abs(score - prev_score) < min_score_delta_for_notify:
                await self._database.upsert_barcello_trigger_state(guild_id, channel_id, stable_color, score, now_iso)
                continue

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

            msg = self._render_barcello_transition(
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
            embed = discord.Embed(
                title="🫛 AGGIORNAMENTO STATO BARCELLO",
                description=msg,
                color=self._barcello_embed_color(stable_color),
            )
            channel = self._bot.get_channel(int(channel_id))
            if channel and isinstance(channel, discord.abc.Messageable) and msg:
                await channel.send(embed=embed)
            await self._database.upsert_barcello_trigger_state(guild_id, channel_id, stored_color, score, now.isoformat())
            await self._database.set_trigger_state(
                guild_id,
                channel_id,
                "barcello_daily",
                {"date": day_key, "counts": counts, "last_entered_ts": last_entered_ts},
            )

    async def _handle_phrases(self, envelope: EventEnvelope) -> None:
        assert envelope.guild_id and envelope.channel_id
        if not await self._database.get_trigger_enabled(envelope.guild_id, envelope.channel_id, "frasi"):
            return
        phrases = await self._database.get_matching_phrases(envelope.guild_id, envelope.channel_id)
        content = envelope.content or ""
        for phrase in phrases:
            if self._phrase_matches(content, phrase):
                await self._reply_phrase(envelope, phrase)
                break

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
        author_name = await self._resolve_phrase_author_name(envelope, channel)

        state = await self._database.get_trigger_state(envelope.guild_id, envelope.channel_id, "frasi")

        previous_seen = self._build_last_seen_values(phrase.get("last_seen_ts"))
        template_kind = "DEFAULT" if phrase.get("last_seen_ts") else "FIRST"
        template = self._resolve_phrase_template(state, author_id=author_id, kind=template_kind)

        count_user = await self._database.increment_phrase_user_stats(phrase_id, author_id, ts, message_id)
        values = {
            "author": f"<@{author_id}>" if author_id else "",
            "author_name": author_name,
            "phrase": str(phrase.get("phrase") or ""),
            "count_user": str(count_user),
            "last_seen_human": previous_seen["human"],
            "last_seen_dt": previous_seen["dt"],
        }
        text = self._render_phrase_template(template, values)
        if message_id:
            try:
                target = await channel.fetch_message(int(message_id))
                await target.reply(text)
            except (discord.NotFound, discord.HTTPException, ValueError):
                await channel.send(text)
        else:
            await channel.send(text)
        await self._database.update_phrase_last_seen(phrase_id, ts, message_id)

    async def _resolve_phrase_author_name(self, envelope: EventEnvelope, channel: discord.TextChannel) -> str:
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

    def _resolve_phrase_template(self, state: dict[str, object], *, author_id: str, kind: str) -> str:
        templates: dict[str, object] = {}
        if isinstance(state.get("templates"), dict):
            templates = dict(state["templates"])
        per_user_templates: dict[str, object] = {}
        if isinstance(state.get("per_user"), dict) and author_id:
            raw = state["per_user"].get(author_id)
            if isinstance(raw, dict):
                per_user_templates = dict(raw)

        selected = per_user_templates.get(kind) or templates.get(kind) or PHRASE_FALLBACK_TEMPLATES[kind]
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
        cache_fragment = "default"
        channel_bundle: dict[str, object] | None = None
        target_ids_fragment = "all"
        if cache_scope != "global":
            user_id = ""
            if isinstance(source, discord.Message):
                user_id = str(source.author.id)
            elif isinstance(source, discord.Interaction):
                user_id = str(source.user.id)
            channel_bundle = await self._build_qna_payload(
                guild_id,
                channel_id,
                question,
                source=source,
                session_user_id=user_id,
            )
            cache_fragment = str(channel_bundle.get("cache_fragment") or cache_fragment)
            target_ids_fragment = str(channel_bundle.get("target_ids_fragment") or target_ids_fragment)
            session_signature = str(channel_bundle.get("session_signature") or "nosession")
        else:
            session_signature = "nosession"
        cache_key = f"qna:{cache_scope}:{cache_channel}:{target_ids_fragment}:{cache_fragment}:{session_signature}:{normalized_question}"
        cached = await self._database.get_cache(cache_key)
        if cached is not None:
            logger.info("qna cache hit scope=%s channel_id=%s", scope, channel_id)
            return {"can_answer": True, "answer": cached, "refusal_reason": None, "evidence_pack": []}

        if scope == "global":
            answer = await self._ask_ai_json(await self._build_qna_global_payload(question))
            if answer and answer.get("can_answer"):
                await self._database.set_cache(cache_key, str(answer.get("answer") or ""), 7 * 24 * 3600)
                answer["evidence_pack"] = []
            return answer

        assert channel_bundle is not None
        empty_reply = str(channel_bundle.get("empty_reply") or "").strip()
        if empty_reply:
            await self._database.set_cache(cache_key, empty_reply, 30 * 60)
            return {"can_answer": True, "answer": empty_reply, "refusal_reason": None, "evidence_pack": channel_bundle.get("evidence_pack", [])}

        payload_obj = json.loads(str(channel_bundle.get("payload") or "{}"))
        payload_obj = self._shrink_payload_for_budget(payload_obj, str(channel_bundle.get("breadth") or "normal"))
        channel_answer = await self._ask_ai_json(json.dumps(payload_obj, ensure_ascii=False))
        ambiguous_note = str(channel_bundle.get("ambiguous_note") or "").strip()
        if channel_answer and channel_answer.get("can_answer") and ambiguous_note:
            answer_text = str(channel_answer.get("answer") or "").strip()
            channel_answer["answer"] = f"{ambiguous_note}\n\n{answer_text}" if answer_text else ambiguous_note

        if channel_answer and channel_answer.get("can_answer"):
            ttl = int(channel_bundle.get("cache_ttl") or 60 * 60)
            await self._database.set_cache(cache_key, str(channel_answer.get("answer") or ""), ttl)
            if channel_bundle.get("session_user_id"):
                await self._store_qna_turn(
                    guild_id,
                    channel_id,
                    str(channel_bundle.get("session_user_id") or ""),
                    question,
                    str(channel_answer.get("answer") or ""),
                )

        if channel_answer and channel_answer.get("can_answer"):
            channel_answer["evidence_pack"] = channel_bundle.get("evidence_pack", [])

        if scope == "channel":
            return channel_answer

        if channel_answer and channel_answer.get("can_answer"):
            return channel_answer
        global_answer = await self._ask_ai_json(await self._build_qna_global_payload(question))
        if not global_answer or not global_answer.get("can_answer"):
            return channel_answer or global_answer
        fallback_text = f"Non trovo abbastanza evidenze nel canale: provo una risposta generale.\n\n{str(global_answer.get('answer') or '').strip()}"
        await self._database.set_cache(f"qna:mixed:global:{normalized_question}", fallback_text, 7 * 24 * 3600)
        return {"can_answer": True, "answer": fallback_text, "refusal_reason": None, "evidence_pack": []}

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

    async def _build_qna_global_payload(self, question: str) -> str:
        prompt = {
            "question": question,
            "constraints": ["risposta generale", "non includere PII", "rispondi in italiano"],
            "output_schema": {"can_answer": "bool", "answer": "string", "refusal_reason": "string|null"},
        }
        return json.dumps(prompt, ensure_ascii=False)

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

    def _build_qna_embed(self, question: str, answer_text: str, evidence: list[dict[str, str]]) -> discord.Embed:
        embed = discord.Embed(
            description=self._truncate_embed_description(self._bulletize_answer(question, answer_text, evidence)),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Barcellometro Q&A")
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
            return f"Non ho trovato prove dirette di un messaggio di {target_raw} nel periodo richiesto."

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
            return f"Non ho trovato prove dirette di un messaggio di {target_raw} nel periodo richiesto."
        return "Non ho trovato prove dirette nel periodo richiesto."

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
        model = self._ai.get_model("summary") or "gpt-4o-mini"
        response = await self._ai.client().responses.create(model=model, input=payload)
        text = getattr(response, "output_text", "") or ""
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
