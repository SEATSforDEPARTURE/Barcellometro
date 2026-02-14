from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord

from app.services.barcello import BarcelloService
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
    ) -> None:
        self._database = database
        self._barcello = barcello
        self._entitlements = entitlements
        self._ai = ai_service
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
        guild_id = str(interaction.guild_id)
        channel_id = str(interaction.channel_id)
        if not await self._database.get_trigger_enabled(guild_id, channel_id, "qna"):
            await interaction.response.send_message("Il trigger Q&A non è abilitato in questo canale.", ephemeral=True)
            return
        if is_out_of_scope_question(question):
            await interaction.response.send_message("Posso rispondere solo su questo canale.", ephemeral=True)
            return
        if is_sensitive_question(question):
            await interaction.response.send_message("Non posso aiutare con dati personali o sensibili.", ephemeral=True)
            return
        limit = await self._resolve_qna_limit(interaction)
        window_date = datetime.now(ROME_TZ).date().isoformat()
        used = await self._database.get_usage(guild_id, str(interaction.user.id), "qna", window_date)
        if used >= limit:
            await interaction.response.send_message("Hai esaurito le domande di oggi.", ephemeral=True)
            return

        payload = await self._build_qna_payload(guild_id, channel_id, question)
        answer = await self._ask_ai_json(payload)
        if answer is None:
            await interaction.response.send_message("AI non disponibile al momento.", ephemeral=True)
            return
        if not answer.get("can_answer"):
            await interaction.response.send_message(answer.get("refusal_reason") or "Non posso rispondere.", ephemeral=True)
            return
        text = str(answer.get("answer") or "").strip()
        if not text:
            await interaction.response.send_message("Risposta non valida.", ephemeral=True)
            return
        if contains_pii(text):
            await interaction.response.send_message("Non posso condividere dati personali.", ephemeral=True)
            return

        await self._database.increment_usage(
            guild_id,
            str(interaction.user.id),
            "qna",
            window_date,
            datetime.now(timezone.utc).isoformat(),
        )
        await interaction.response.send_message(text)

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
        payload = await self._build_qna_payload(guild_id, channel_id, question)
        answer = await self._ask_ai_json(payload)
        if answer is None or not answer.get("can_answer"):
            await message.reply((answer or {}).get("refusal_reason") or "Non posso rispondere.")
            return
        text = str(answer.get("answer") or "").strip()
        if not text or contains_pii(text):
            await message.reply("Non posso condividere dati personali.")
            return
        await self._database.increment_usage(guild_id, str(message.author.id), "qna", window_date, datetime.now(timezone.utc).isoformat())
        await message.reply(text)

    async def _barcello_loop(self) -> None:
        while True:
            try:
                await self._poll_barcello()
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
        raw_templates = config.get("templates")
        templates = raw_templates if isinstance(raw_templates, dict) else {}
        rows = await self._database.list_enabled_trigger_channels("barcello")
        for row in rows:
            guild_id = str(row["guild_id"])
            channel_id = str(row["channel_id"])
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

    async def _resolve_qna_limit(self, interaction: discord.Interaction) -> int:
        profile = await self._entitlements.resolve_profile(interaction.user)
        raw = await self._database.get_setting("qna.daily_limits")
        defaults = {"base": 0, "role1": 1, "role2": 2, "role3": 3, "mod": 999}
        if not raw:
            return int(defaults.get(profile, defaults["base"]))
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = defaults
        if not isinstance(parsed, dict):
            parsed = defaults
        return int(parsed.get(profile, parsed.get("base", 0)))

    async def _resolve_qna_limit_for_member(self, member) -> int:
        profile = await self._entitlements.resolve_profile(member)
        raw = await self._database.get_setting("qna.daily_limits")
        defaults = {"base": 0, "role1": 1, "role2": 2, "role3": 3, "mod": 999}
        if not raw:
            return int(defaults.get(profile, defaults["base"]))
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = defaults
        if not isinstance(parsed, dict):
            parsed = defaults
        return int(parsed.get(profile, parsed.get("base", 0)))

    async def _build_qna_payload(self, guild_id: str, channel_id: str, question: str) -> str:
        now = datetime.now(ROME_TZ)
        day_start = datetime.combine(now.date(), datetime.min.time(), tzinfo=ROME_TZ).astimezone(timezone.utc)
        rows = await self._database.fetchall(
            """
            SELECT author_id, COUNT(*) as c
            FROM messages
            WHERE guild_id = ? AND channel_id = ? AND ts >= ?
            GROUP BY author_id
            ORDER BY c DESC
            LIMIT 5
            """,
            (guild_id, channel_id, day_start.isoformat()),
        )
        top = [{"author_id": r["author_id"], "count": int(r["c"])} for r in rows]
        total_row = await self._database.fetchone(
            "SELECT COUNT(*) AS c FROM messages WHERE guild_id = ? AND channel_id = ? AND ts >= ?",
            (guild_id, channel_id, day_start.isoformat()),
        )
        total = int(total_row["c"]) if total_row else 0
        latest = await self._database.fetch_messages_in_range(channel_id=channel_id, start_ts=day_start.isoformat(), end_ts=datetime.now(timezone.utc).isoformat(), limit=30)
        recent = [str(m["content"] or "") for m in latest][-30:]
        prompt = {
            "question": question,
            "constraints": ["solo canale corrente", "non includere PII", "rispondi in italiano"],
            "context": {"total_messages_today": total, "top_talkers_today": top, "recent_messages": recent},
            "output_schema": {"can_answer": "bool", "answer": "string", "refusal_reason": "string|null"},
        }
        return json.dumps(prompt, ensure_ascii=False)

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
    needles = ["altro canale", "privato", "salottino", "dm", "sezione privata", "cosa dicono in", "nel canale"]
    return any(n in q for n in needles)


def is_sensitive_question(question: str) -> bool:
    q = question.lower()
    needles = ["numero", "telefono", "indirizzo", "email", "contatto", "iban", "carta", "codice fiscale", "documento"]
    return any(n in q for n in needles)
