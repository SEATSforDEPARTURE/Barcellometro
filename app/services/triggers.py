from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
BARCELLO_TRIGGER_CONFIG_PATH = "settings/barcello_trigger.json"


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
        self._barcello_cooldown: dict[str, datetime] = {}

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

    async def handle_qna_question(self, interaction: discord.Interaction, question: str) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("Usa questo comando in un canale.", ephemeral=True)
            return
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        if not await self._database.get_trigger_enabled(guild_id, channel_id, "qna"):
            await interaction.followup.send("Il trigger Q&A non è abilitato in questo canale.", ephemeral=True)
            return
        if is_out_of_scope_question(question):
            await interaction.followup.send("Posso rispondere solo su questo canale.", ephemeral=True)
            return
        if is_sensitive_question(question):
            await interaction.followup.send("Non posso aiutare con dati personali o sensibili.", ephemeral=True)
            return
        limit = await self._resolve_qna_limit(interaction)
        window_date = datetime.now(ROME_TZ).date().isoformat()
        used = await self._database.get_usage(guild_id, str(interaction.user.id), "qna", window_date)
        if used >= limit:
            await interaction.followup.send("Hai esaurito le domande di oggi.", ephemeral=True)
            return

        scope = await self._decide_qna_scope(question)
        answer = await self._handle_qna(
            scope=scope,
            guild_id=guild_id,
            channel_id=channel_id,
            question=question,
            source=interaction,
        )
        if answer is None:
            await interaction.followup.send("AI non disponibile al momento.", ephemeral=True)
            return
        if not answer.get("can_answer"):
            await interaction.followup.send(answer.get("refusal_reason") or "Non posso rispondere.", ephemeral=True)
            return
        text = str(answer.get("answer") or "").strip()
        if not text:
            await interaction.followup.send("Risposta non valida.", ephemeral=True)
            return
        if contains_pii(text):
            await interaction.followup.send("Non posso condividere dati personali.", ephemeral=True)
            return

        await self._database.increment_usage(
            guild_id,
            str(interaction.user.id),
            "qna",
            window_date,
            datetime.now(timezone.utc).isoformat(),
        )
        await interaction.followup.send(text, ephemeral=True)

    async def handle_message_qna(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        question = message.content.strip()
        if not question:
            return
        if "?" not in question and not question.lower().startswith("domanda:"):
            return
        guild_id = str(message.guild.id)
        channel_id = str(message.channel.id)
        if not await self._database.get_trigger_enabled(guild_id, channel_id, "qna"):
            return
        if is_out_of_scope_question(question):
            await message.reply("Posso rispondere solo su questo canale.")
            return
        if is_sensitive_question(question):
            await message.reply("Non posso aiutare con dati personali o sensibili.")
            return
        limit = await self._resolve_qna_limit_for_member(message.author)
        window_date = datetime.now(ROME_TZ).date().isoformat()
        used = await self._database.get_usage(guild_id, str(message.author.id), "qna", window_date)
        if used >= limit:
            await message.reply("Hai esaurito le domande di oggi.")
            return
        scope = await self._decide_qna_scope(question)
        answer = await self._handle_qna(
            scope=scope,
            guild_id=guild_id,
            channel_id=channel_id,
            question=question,
            source=message,
        )
        if answer is None or not answer.get("can_answer"):
            await message.reply((answer or {}).get("refusal_reason") or "Non posso rispondere.")
            return
        text = str(answer.get("answer") or "").strip()
        if not text or contains_pii(text):
            await message.reply("Non posso condividere dati personali.")
            return
        await self._database.increment_usage(guild_id, str(message.author.id), "qna", window_date, datetime.now(timezone.utc).isoformat())
        await message.reply(text)

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
        raw_templates = config.get("templates")
        templates = raw_templates if isinstance(raw_templates, dict) else {}
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
            stored_color = color or ""
            score = int(status.get("score") or 0)
            prev = await self._database.get_barcello_trigger_state(guild_id, channel_id)
            prev_color = self._normalize_barcello_color(prev.get("last_color") if prev else None)
            prev_score = int(prev.get("last_score")) if prev and prev.get("last_score") is not None else None
            now = datetime.now(timezone.utc)
            cooldown_key = f"{guild_id}:{channel_id}"
            last_sent = self._barcello_cooldown.get(cooldown_key)
            if last_sent and (now - last_sent) < timedelta(minutes=10):
                await self._database.upsert_barcello_trigger_state(guild_id, channel_id, stored_color, score, now.isoformat())
                continue
            if prev_color and prev_score is not None:
                if color == prev_color and abs(score - prev_score) < 5:
                    await self._database.upsert_barcello_trigger_state(guild_id, channel_id, stored_color, score, now.isoformat())
                    continue
            msg = self._render_barcello_transition(prev_color, stored_color, prev_score, score, templates=templates)
            channel = self._bot.get_channel(int(channel_id))
            if channel and isinstance(channel, discord.abc.Messageable) and msg:
                await channel.send(msg)
                self._barcello_cooldown[cooldown_key] = now
            await self._database.upsert_barcello_trigger_state(guild_id, channel_id, stored_color, score, now.isoformat())

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
        ts = datetime.now(timezone.utc).isoformat()
        message_id = str(envelope.meta.get("message_id") or "")
        if phrase.get("last_seen_ts"):
            try:
                delta = datetime.now(timezone.utc) - datetime.fromisoformat(str(phrase["last_seen_ts"]))
                total_min = int(delta.total_seconds() // 60)
                human = f"{total_min} minuti" if total_min < 120 else f"{total_min // 60} ore"
            except ValueError:
                human = "un po' di tempo"
            text = f"Questa frase è riapparsa! Ultima volta: {human} fa."
        else:
            text = "Frase rilevata per la prima volta in questo trigger."
        if message_id:
            try:
                target = await channel.fetch_message(int(message_id))
                await target.reply(text)
            except (discord.NotFound, discord.HTTPException, ValueError):
                await channel.send(text)
        else:
            await channel.send(text)
        await self._database.update_phrase_last_seen(int(phrase["id"]), ts, message_id)

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

    def _render_barcello_transition(
        self,
        old: str | None,
        new: str,
        old_score: int | None,
        new_score: int,
        templates: dict[str, str] | None = None,
    ) -> str:
        worsening = {"VERDE": 0, "GIALLO": 1, "ROSSO": 2, "NERO": 3}
        template_dict = templates if isinstance(templates, dict) else {}
        values = {
            "old": old or "",
            "new": new,
            "old_score": "" if old_score is None else str(old_score),
            "new_score": str(new_score),
        }

        def render_template(message_template: str | None) -> str | None:
            if not isinstance(message_template, str):
                return None
            return re.sub(r"\{(old|new|old_score|new_score)\}", lambda match: values[match.group(1)], message_template)

        if old is None:
            return render_template(template_dict.get("INIT")) or f"📌 Barcello ora {new} (score {new_score})"

        severity_new = worsening.get(new, 99)
        severity_old = worsening.get(old, 99)

        if old != new:
            exact_template = render_template(template_dict.get(f"{old}->{new}"))
            if exact_template:
                return exact_template

        if severity_new > severity_old:
            return render_template(template_dict.get("WORSEN")) or f"⚠️ Barcello peggiora: {old} → {new} ({old_score}→{new_score})."
        if severity_new < severity_old:
            return render_template(template_dict.get("IMPROVE")) or f"✅ Barcello migliora: {old} → {new} ({old_score}→{new_score})."
        return render_template(template_dict.get("SAME")) or f"Barcello aggiornato: {new_score}."

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
        if cache_scope != "global":
            channel_bundle = await self._build_qna_payload(guild_id, channel_id, question, source=source)
            cache_fragment = str(channel_bundle.get("cache_fragment") or cache_fragment)
        cache_key = f"qna:{cache_scope}:{cache_channel}:{cache_fragment}:{normalized_question}"
        cached = await self._database.get_cache(cache_key)
        if cached is not None:
            logger.info("qna cache hit scope=%s channel_id=%s", scope, channel_id)
            return {"can_answer": True, "answer": cached, "refusal_reason": None}

        if scope == "global":
            answer = await self._ask_ai_json(await self._build_qna_global_payload(question))
            if answer and answer.get("can_answer"):
                await self._database.set_cache(cache_key, str(answer.get("answer") or ""), 7 * 24 * 3600)
            return answer

        assert channel_bundle is not None
        empty_reply = str(channel_bundle.get("empty_reply") or "").strip()
        if empty_reply:
            await self._database.set_cache(cache_key, empty_reply, 30 * 60)
            return {"can_answer": True, "answer": empty_reply, "refusal_reason": None}

        channel_answer = await self._ask_ai_json(str(channel_bundle.get("payload") or "{}"))
        ambiguous_note = str(channel_bundle.get("ambiguous_note") or "").strip()
        if channel_answer and channel_answer.get("can_answer") and ambiguous_note:
            answer_text = str(channel_answer.get("answer") or "").strip()
            channel_answer["answer"] = f"{ambiguous_note}\n\n{answer_text}" if answer_text else ambiguous_note
        if scope == "channel":
            if channel_answer and channel_answer.get("can_answer"):
                ttl = int(channel_bundle.get("cache_ttl") or 60 * 60)
                await self._database.set_cache(cache_key, str(channel_answer.get("answer") or ""), ttl)
            return channel_answer

        # mixed scope
        if channel_answer and channel_answer.get("can_answer"):
            ttl = int(channel_bundle.get("cache_ttl") or 60 * 60)
            await self._database.set_cache(cache_key, str(channel_answer.get("answer") or ""), ttl)
            return channel_answer
        global_answer = await self._ask_ai_json(await self._build_qna_global_payload(question))
        if not global_answer or not global_answer.get("can_answer"):
            return channel_answer or global_answer
        fallback_text = f"Non trovo abbastanza evidenze nel canale: provo una risposta generale.\n\n{str(global_answer.get('answer') or '').strip()}"
        await self._database.set_cache(f"qna:mixed:global:{normalized_question}", fallback_text, 7 * 24 * 3600)
        return {"can_answer": True, "answer": fallback_text, "refusal_reason": None}

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

    async def _resolve_qna_limit(self, interaction: discord.Interaction) -> int:
        profile = await self._entitlements.resolve_profile(interaction.user)
        raw = await self._database.get_setting("qna.daily_limits")
        defaults = {"base": 0, "role1": 1, "role2": 2, "role3": 3, "mod": 999}
        if not raw:
            tier_limit = int(defaults.get(profile, defaults["base"]))
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = defaults
            if not isinstance(parsed, dict):
                parsed = defaults
            tier_limit = int(parsed.get(profile, parsed.get("base", 0)))
        if interaction.guild_id is None:
            return tier_limit
        bonus, _ = await self._database.get_qna_bonus(str(interaction.guild_id), str(interaction.user.id))
        return tier_limit + max(0, bonus)

    async def _resolve_qna_limit_for_member(self, member) -> int:
        profile = await self._entitlements.resolve_profile(member)
        raw = await self._database.get_setting("qna.daily_limits")
        defaults = {"base": 0, "role1": 1, "role2": 2, "role3": 3, "mod": 999}
        if not raw:
            tier_limit = int(defaults.get(profile, defaults["base"]))
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = defaults
            if not isinstance(parsed, dict):
                parsed = defaults
            tier_limit = int(parsed.get(profile, parsed.get("base", 0)))
        guild = getattr(member, "guild", None)
        if guild is None:
            return tier_limit
        bonus, _ = await self._database.get_qna_bonus(str(guild.id), str(member.id))
        return tier_limit + max(0, bonus)

    async def _build_qna_payload(
        self,
        guild_id: str,
        channel_id: str,
        question: str,
        *,
        source: discord.Interaction | discord.Message | None = None,
    ) -> dict[str, object]:
        guild = source.guild if source else None
        target_member, ambiguous_note = self._infer_target_member_with_note(source, question, guild)
        start_dt, end_dt, range_label = self.infer_time_range(question, person_focused=target_member is not None)
        start_iso = start_dt.isoformat()
        end_iso = end_dt.isoformat()
        logger.info(
            "qna inferred range channel_id=%s label=%s start=%s end=%s target_user=%s",
            channel_id,
            range_label,
            start_iso,
            end_iso,
            str(target_member.id) if target_member else "none",
        )

        rows = await self._database.fetchall(
            """
            SELECT author_id, COUNT(*) as c
            FROM messages AS m
            LEFT JOIN users AS u ON u.user_id = m.author_id
            WHERE m.guild_id = ? AND m.channel_id = ? AND m.ts >= ? AND m.ts <= ?
              AND COALESCE(m.is_deleted, 0) = 0
              AND COALESCE(u.is_bot, 0) = 0
            GROUP BY author_id
            ORDER BY c DESC
            LIMIT 5
            """,
            (guild_id, channel_id, start_iso, end_iso),
        )
        top = [{"author_id": r["author_id"], "count": int(r["c"])} for r in rows]
        total_row = await self._database.fetchone(
            """
            SELECT COUNT(*) AS c
            FROM messages AS m
            LEFT JOIN users AS u ON u.user_id = m.author_id
            WHERE m.guild_id = ? AND m.channel_id = ? AND m.ts >= ? AND m.ts <= ?
              AND COALESCE(m.is_deleted, 0) = 0
              AND COALESCE(u.is_bot, 0) = 0
            """,
            (guild_id, channel_id, start_iso, end_iso),
        )
        total = int(total_row["c"]) if total_row else 0
        bucketed = await self._database.fetch_messages_in_range_time_bucketed(
            channel_id=channel_id,
            start_ts=start_iso,
            end_ts=end_iso,
            buckets=8,
            per_bucket_limit=10,
            include_bots=False,
        )
        recent = [self._truncate_text(str(m["content"] or ""), 280) for m in bucketed][-80:]

        context: dict[str, object] = {
            "time_range_label": range_label,
            "start": start_iso,
            "end": end_iso,
            "total_messages": total,
            "top_talkers": top,
            "recent_messages": recent,
        }
        constraints = ["solo canale corrente", "non includere PII", "rispondi in italiano"]
        cache_ttl = 60 * 60
        empty_reply = ""
        if target_member is not None:
            target_rows = await self._database.fetchall(
                """
                SELECT m.ts, m.content
                FROM messages AS m
                LEFT JOIN users AS u ON u.user_id = m.author_id
                WHERE m.channel_id = ?
                  AND m.author_id = ?
                  AND m.ts >= ?
                  AND m.ts <= ?
                  AND COALESCE(m.is_deleted, 0) = 0
                  AND COALESCE(u.is_bot, 0) = 0
                ORDER BY m.ts ASC
                LIMIT 200
                """,
                (channel_id, str(target_member.id), start_iso, end_iso),
            )
            sampled_rows = self._sample_messages(list(target_rows), keep_start=20, keep_end=80)
            target_messages = [
                {"created_at": str(r["ts"] or ""), "content": self._truncate_text(str(r["content"] or ""), 350)}
                for r in sampled_rows
                if str(r["content"] or "").strip()
            ]
            if not target_messages:
                display_name = target_member.display_name
                empty_reply = (
                    f"Non ho trovato messaggi di {display_name} nel periodo richiesto ({range_label}). "
                    "Prova con una finestra più ampia, ad esempio 'ultimi 7 giorni'."
                )
            channel_context = [
                self._truncate_text(str(r["content"] or ""), 240)
                for r in bucketed[-20:]
                if str(r["content"] or "").strip()
            ]
            context.update(
                {
                    "target_user": {"id": str(target_member.id), "display_name": target_member.display_name},
                    "target_messages": target_messages,
                    "channel_context": channel_context,
                    "focus_instruction": (
                        "Riassumi cosa ha scritto di interessante "
                        f"{target_member.display_name} nel periodo {range_label}. "
                        "Evidenzia temi, momenti, 2-3 citazioni brevi se presenti. "
                        "Se non ci sono abbastanza messaggi, dillo chiaramente."
                    ),
                }
            )
            cache_ttl = 60 * 60
        else:
            context["focus_instruction"] = "Riassumi i temi rilevanti nel canale per il periodo indicato."
            cache_ttl = 45 * 60

        prompt = {
            "question": question,
            "constraints": constraints,
            "context": context,
            "output_schema": {"can_answer": "bool", "answer": "string", "refusal_reason": "string|null"},
        }
        target_key = str(target_member.id) if target_member else "all"
        cache_fragment = f"{channel_id}:{target_key}:{start_iso}:{end_iso}"
        return {
            "payload": json.dumps(prompt, ensure_ascii=False),
            "cache_fragment": cache_fragment,
            "cache_ttl": cache_ttl,
            "empty_reply": empty_reply,
            "ambiguous_note": ambiguous_note,
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

        today_start = datetime.combine(now_local.date(), datetime.min.time(), tzinfo=local_tz)
        if "ultima ora" in q or "ultim'ora" in q:
            return now_utc - timedelta(hours=1), now_utc, "ultima ora"
        if (m := re.search(r"ultime\s+(\d{1,2})\s+ore", q)):
            hours = max(1, int(m.group(1)))
            return now_utc - timedelta(hours=hours), now_utc, f"ultime {hours} ore"
        if (m := re.search(r"ultimi\s+(\d{1,2})\s+giorni", q)):
            days = min(30, max(1, int(m.group(1))))
            return now_utc - timedelta(days=days), now_utc, f"ultimi {days} giorni"
        if "stamattina" in q:
            morning = today_start + timedelta(hours=6)
            return as_utc(morning), now_utc, "stamattina"
        if "questa sera" in q:
            evening = today_start + timedelta(hours=18)
            return as_utc(evening), now_utc, "questa sera"
        if "ieri" in q:
            yesterday_start = today_start - timedelta(days=1)
            return as_utc(yesterday_start), as_utc(today_start), "ieri"
        if "oggi" in q:
            return as_utc(today_start), now_utc, "oggi"
        if "questa settimana" in q:
            week_start = today_start - timedelta(days=today_start.weekday())
            return as_utc(week_start), now_utc, "questa settimana"
        default_hours = 24 if person_focused else 6
        return now_utc - timedelta(hours=default_hours), now_utc, f"ultime {default_hours} ore"

    def infer_target_member(
        self,
        interaction_or_message: discord.Interaction | discord.Message | None,
        question: str,
        guild: discord.Guild | None,
    ) -> discord.Member | None:
        target, _ = self._infer_target_member_with_note(interaction_or_message, question, guild)
        return target

    def _infer_target_member_with_note(
        self,
        interaction_or_message: discord.Interaction | discord.Message | None,
        question: str,
        guild: discord.Guild | None,
    ) -> tuple[discord.Member | None, str]:
        if guild is None:
            return None, ""
        mention_match = re.search(r"<@!?(\d+)>", question)
        if mention_match:
            member = guild.get_member(int(mention_match.group(1)))
            if member and not member.bot:
                return member, ""
        if isinstance(interaction_or_message, discord.Message):
            for member in interaction_or_message.mentions:
                if not member.bot:
                    return member, ""
        if isinstance(interaction_or_message, discord.Interaction):
            data = interaction_or_message.data if isinstance(interaction_or_message.data, dict) else {}
            resolved = data.get("resolved") if isinstance(data, dict) else None
            users = resolved.get("users") if isinstance(resolved, dict) else None
            if isinstance(users, dict):
                for user_id in users.keys():
                    member = guild.get_member(int(user_id))
                    if member and not member.bot:
                        return member, ""

        candidates = [token for token in re.findall(r"\b[\wÀ-ÿ']+\b", question) if len(token) > 2]
        stopwords = {"che", "cosa", "oggi", "ieri", "interessante", "ha", "scritto", "nel", "canale", "questa", "settimana"}
        name_tokens = [t for t in candidates if t[0].isupper() and t.lower() not in stopwords]
        if not name_tokens:
            name_tokens = [t for t in candidates if t.lower() not in stopwords][:1]
        if not name_tokens:
            return None, ""
        token = name_tokens[0].lower()

        prefix_matches = [
            m
            for m in guild.members
            if not m.bot and (m.display_name.lower().startswith(token) or m.name.lower().startswith(token))
        ]
        if len(prefix_matches) == 1:
            return prefix_matches[0], ""
        if len(prefix_matches) > 1:
            return None, "Non sono sicuro di chi intendi. Intanto rispondo sul canale."

        choices: dict[str, discord.Member] = {}
        for member in guild.members:
            if member.bot:
                continue
            choices[member.display_name.lower()] = member
            choices[member.name.lower()] = member
        close = difflib.get_close_matches(token, list(choices.keys()), n=2, cutoff=0.9)
        if len(close) == 1:
            return choices[close[0]], ""
        if len(close) > 1:
            return None, "Non sono sicuro di chi intendi. Intanto rispondo sul canale."
        return None, ""

    def _truncate_text(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return f"{text[: max_chars - 1]}…"

    def _sample_messages(self, rows: list[object], *, keep_start: int, keep_end: int) -> list[object]:
        if len(rows) <= keep_start + keep_end:
            return rows
        return rows[:keep_start] + rows[-keep_end:]

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
