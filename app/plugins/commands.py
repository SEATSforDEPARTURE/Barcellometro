from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import discord
from discord import app_commands

from app.core.service_registry import ServiceRegistry
from app.services.barcello import BarcelloService
from app.services.entitlements import EntitlementsService
from app.services.ingest import EventEnvelope, IngestService

logger = logging.getLogger(__name__)


def setup(registry: ServiceRegistry) -> None:
    bot: discord.Client = registry.get("bot")
    database = registry.get("database")
    entitlements = EntitlementsService(database)
    registry.register("entitlements", entitlements)
    barcello = BarcelloService(database)
    registry.register("barcello", barcello)
    retention = registry.get("retention")
    backfill = registry.get("backfill")
    guard = registry.get("guard")
    status_service = registry.get("status")
    ai_service = registry.get("ai")
    voice_ingest = registry.get("voice_ingest") if registry.has("voice_ingest") else None
    ingest: IngestService = registry.get("ingest")
    config = registry.get("config")

    guild = discord.Object(id=config.guild_id)

    barcellometro_group = app_commands.Group(name="barcellometro", description="Controlli Barcellometro")
    role_group = app_commands.Group(name="role", description="Gestione permessi e limiti")
    stt_group = app_commands.Group(name="stt", description="Impostazioni STT")
    translate_group = app_commands.Group(name="translate", description="Impostazioni traduzione")
    audio_notes_group = app_commands.Group(name="audio_notes", description="Note vocali")
    voice_ingest_group = app_commands.Group(name="voice_ingest", description="Ingest da canale vocale")
    privacy_group = app_commands.Group(name="privacy", description="Privacy per voice ingest")
    status_group = app_commands.Group(name="status", description="Stato servizi")
    barcellometro_group.add_command(role_group)
    barcellometro_group.add_command(stt_group)
    barcellometro_group.add_command(translate_group)
    barcellometro_group.add_command(audio_notes_group)
    barcellometro_group.add_command(voice_ingest_group)

    async def check_permission(interaction: discord.Interaction, command_name: str) -> bool:
        guild = interaction.guild
        is_admin = bool(guild and interaction.user.guild_permissions.administrator)
        role_ids = [role.id for role in getattr(interaction.user, "roles", [])]
        result = await guard.check_command(
            guild_id=interaction.guild_id,
            user_id=interaction.user.id,
            role_ids=role_ids,
            command=command_name,
            is_admin=is_admin,
        )
        if result.allowed:
            return True
        message = result.reason
        if result.remaining is not None:
            message += f" Utilizzi rimanenti: {result.remaining}."
        if result.cooldown_remaining is not None:
            message += f" Cooldown: {result.cooldown_remaining}s."
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)
        return False

    async def ensure_admin(interaction: discord.Interaction) -> bool:
        guild = interaction.guild
        is_admin = bool(guild and interaction.user.guild_permissions.administrator)
        if is_admin:
            return True
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send("Solo admin.", ephemeral=ephemeral)
        else:
            await interaction.response.send_message("Solo admin.", ephemeral=ephemeral)
        return False

    async def set_setting(key: str, value: str) -> None:
        await database.set_setting(key, value)

    async def get_setting(key: str, default: str) -> str:
        stored = await database.get_setting(key)
        return stored if stored is not None else default

    async def send_ephemeral(interaction: discord.Interaction, message: str) -> None:
        ephemeral = interaction.guild_id is not None
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)

    def _render_health_bar(score: int, color_emoji: str) -> str:
        score = max(0, min(100, score))
        filled = int(round(score / 10))
        empty = max(0, 10 - filled)
        return f"{color_emoji * filled}{'⚪' * empty}"

    def _health_description(score: int) -> str:
        if score >= 90:
            return "Ottima! 😄 Il clima è disteso, positivo e molto ricettivo."
        if score >= 75:
            return "Molto buona. 😊 La conversazione scorre senza attriti."
        if score >= 60:
            return "Buona. 😃 Il clima è stabile, con lievi variazioni."
        if score >= 45:
            return "Discreta. 🤔 Clima gestibile ma con primi segnali di tensione."
        if score >= 30:
            return "Delicata. 😬 Il clima richiede cautela."
        return "Critica. 🚨 Situazione tesa e facilmente infiammabile."

    def _alert_message(score: int, color_label: str | None = None) -> str:
        if color_label:
            normalized = color_label.lower()
            if normalized == "verde":
                return "È un buon momento per scrivere e partecipare 💬"
            if normalized == "giallo":
                return "Clima un po’ teso: scrivi con calma e chiarisci se serve 🙂"
            if normalized == "rosso":
                return "Tensione alta: evita provocazioni e abbassa i toni 🧯"
            if normalized == "nero":
                return "Situazione critica: meglio fermarsi e moderare subito 🚨"
        if score >= 60:
            return "È un buon momento per scrivere e partecipare 💬"
        if score >= 45:
            return "Meglio fare attenzione ⚠️ Mantieni un tono neutro."
        if score >= 30:
            return "Situazione delicata 🟠 Meglio osservare."
        return "Alta tensione 🔴 È consigliato non intervenire ora."

    def _trend_display(trend: dict[str, Any]) -> tuple[str, str]:
        direction = trend.get("direction", "stable")
        delta = trend.get("delta", 0)
        mapping = {
            "improving": ("IN MIGLIORAMENTO", "😄"),
            "stable": ("STABILE", "😐"),
            "worsening": ("IN PEGGIORAMENTO", "😟"),
        }
        label, emoji = mapping.get(direction, ("STABILE", "😐"))
        return f"**{label}** {emoji}  *(Δ {delta})*", label

    def _format_metrics(metrics: dict[str, Any]) -> str:
        keys = [
            "message_count",
            "window_minutes",
            "msg_per_min",
            "caps_ratio",
            "negativity_hits",
            "mention_count",
            "mention_per_min",
            "reply_war",
            "top1_author_share",
            "top3_author_share",
            "max_msgs_per_minute",
            "std_msgs_per_minute",
            "burst_ratio",
            "contrast_per_msg",
            "challenge_per_msg",
            "playful_emoji_ratio",
            "passive_aggressive_emoji_ratio",
            "sarcasm_marker_hits",
        ]
        lines = [f"{key}: {metrics.get(key)}" for key in keys]
        return "```\n" + "\n".join(lines) + "\n```"

    def _with_spacing(text: str) -> str:
        return text

    def _add_section(embed: discord.Embed, *, name: str, value: str) -> None:
        embed.add_field(name=name, value=value, inline=False)

    def _parse_hex_color(raw: str | None) -> int | None:
        if not raw:
            return None
        value = raw.strip().lower()
        if value.startswith("#"):
            value = value[1:]
        if value.startswith("0x"):
            value = value[2:]
        try:
            return int(value, 16)
        except ValueError:
            return None

    async def _get_details_embed_color(profile: str) -> int:
        default_color = 0x95A5A6
        mod_color = 0x5865F2
        admin_color = 0x9B59B6
        if profile == "admin":
            stored = await get_setting("barcello.details_color_admin", "")
            return _parse_hex_color(stored) or admin_color
        if profile == "mod":
            stored = await get_setting("barcello.details_color_mod", "")
            return _parse_hex_color(stored) or mod_color
        stored = await get_setting("barcello.details_color_default", "")
        return _parse_hex_color(stored) or default_color

    async def _get_tier_label(profile: str) -> str:
        # Optional manual override for tier labels if you want a name different from the Discord role.
        stored = await get_setting(f"barcello.tier_label.{profile}", "")
        if stored:
            return stored
        defaults = {
            "base": "Utente",
            "role1": "Utente",
            "role2": "Utente",
            "role3": "Utente",
            "mod": "Mod",
            "admin": "Admin",
        }
        return defaults.get(profile, "Utente")

    async def _resolve_tier_display_name(
        *,
        profile: str,
        winner_role_id: str | None,
        guild: discord.Guild | None,
    ) -> str:
        if profile in {"mod", "admin"}:
            return await _get_tier_label(profile)
        if winner_role_id and guild:
            role = guild.get_role(int(winner_role_id))
            if role:
                logger.info("barcello: resolved tier role name=%s (id=%s)", role.name, winner_role_id)
                return role.name
        return await _get_tier_label(profile)

    def _bullet_list(lines: list[str]) -> str:
        cleaned: list[str] = []
        for line in lines:
            text = line.strip()
            if not text:
                continue
            if len(text) > 120:
                text = f"{text[:117]}..."
            cleaned.append(text)
        return "\n".join(f"• {line}" for line in cleaned)

    def _format_motivations(reasons: list[dict[str, Any]]) -> str:
        lines = [f"{reason['label']} ({reason['summary']})" for reason in reasons][:4]
        if not lines:
            return "• (nessuna)"
        return _bullet_list(lines)

    def _normalize_bullets(text: str) -> str:
        lines: list[str] = []
        for line in text.splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            cleaned = cleaned.lstrip("-• ").strip()
            if cleaned:
                lines.append(cleaned)
        if not lines:
            return "• (nessuna)"
        return _bullet_list(lines)

    def _fallback_personal_advice(color_label: str) -> list[str]:
        if color_label == "verde":
            return [
                "Coinvolgi i nuovi: fai una domanda leggera.",
                "Mantieni il ritmo: alterna messaggi brevi e chiari.",
                "Rinforza i contributi positivi con un semplice 👍.",
            ]
        if color_label == "giallo":
            return [
                "Usa un tono neutro e fai domande aperte.",
                "Evita ironie: meglio chiarezza e messaggi brevi.",
                "Se serve, sposta un tema caldo in privato.",
            ]
        return [
            "Evita interventi diretti: favorisci de-escalation o pausa.",
            "Se scrivi, resta neutro e invita al rispetto reciproco.",
            "Rimanda i temi caldi a un momento più tranquillo.",
        ]

    def _fallback_mod_advice(color_label: str) -> list[str]:
        if color_label == "verde":
            return [
                "Monitora senza intervenire: lascia spazio alla conversazione.",
                "Premia i toni costruttivi con una reazione rapida.",
                "Se emergono tensioni, suggerisci un cambio di topic leggero.",
            ]
        if color_label == "giallo":
            return [
                "Intervieni presto con un richiamo soft sui toni.",
                "Invita a chiarire in privato i punti più spinosi.",
                "Riduci il rumore: chiedi messaggi sintetici.",
            ]
        return [
            "Valuta un intervento pubblico di de-escalation.",
            "Se necessario, sposta la discussione su un topic neutro.",
            "Monitora utenti/coppie ricorrenti e intervieni in privato.",
        ]

    def _build_barcello_public_embed(
        *,
        result: BarcelloResult,
        channel_name: str,
        window_minutes: int,
    ) -> discord.Embed:
        color_label = (result.color or "nero").lower()
        color_map = {
            "verde": (0x2ECC71, "🟢", "verde"),
            "giallo": (0xF1C40F, "🟡", "giallo"),
            "rosso": (0xE74C3C, "🔴", "rosso"),
            "nero": (0x2C2F33, "⚫", "nero"),
        }
        embed_color, emoji, label = color_map.get(color_label, (0x2C2F33, "⚫", color_label))
        title_channel = channel_name or "canale"
        description_lines = [
            f"🕒 **Ultimi {window_minutes} minuti**",
            "",
            f"{emoji} **ALLERTA {label.upper()}**",
            f"*{_alert_message(result.score, label)}*",
        ]
        embed = discord.Embed(
            title=f"🫛 **STATO BARCELLO “{title_channel}”**",
            description="\n".join(description_lines),
            color=embed_color,
        )
        bar = _render_health_bar(result.score, emoji)
        _add_section(
            embed,
            name="🫀 **PUNTI SALUTE**",
            value=_with_spacing(f"{bar}  **({result.score}/100)**\n*{_health_description(result.score)}*"),
        )
        embed.set_footer(text="Barcellometro")
        return embed

    def _build_barcello_details_embed(
        *,
        result: BarcelloResult,
        output_flags: dict[str, Any],
        profile: str,
        tier_display_name: str,
        embed_color: int,
        reasons_text: str,
        trend_text: str,
        personal_advice: list[str],
        mod_advice: list[str],
        ai_note: str,
    ) -> discord.Embed:
        embed = discord.Embed(title=f"🧾 **DETTAGLI BARCELLO — {tier_display_name}**", color=embed_color)
        if output_flags.get("show_motivation") and reasons_text:
            _add_section(embed, name="🔥 **MOTIVAZIONI**", value=_with_spacing(reasons_text))
        if output_flags.get("show_trend") and (result.trend or trend_text):
            if trend_text:
                trend_value = trend_text
            else:
                trend_value, _ = _trend_display(result.trend)
            _add_section(embed, name="📈 **TREND**", value=_with_spacing(trend_value))
        if output_flags.get("show_advice"):
            advice_lines = personal_advice[:5]
            if advice_lines:
                _add_section(embed, name="🧠 **CONSIGLI PERSONALIZZATI**", value=_bullet_list(advice_lines))
        if profile == "mod" and output_flags.get("show_advice"):
            mod_lines = mod_advice[:5]
            if mod_lines:
                _add_section(embed, name="🛡️ **CONSIGLI PER LA MODERAZIONE**", value=_bullet_list(mod_lines))
        if output_flags.get("show_mod_metrics") and profile == "mod":
            _add_section(embed, name="🧮 **METRICHE AGGREGATE**", value=_with_spacing(_format_metrics(result.metrics)))
        if ai_note:
            _add_section(embed, name="ℹ️ **NOTA**", value=_with_spacing(ai_note))
        notes_by_profile = {
            "base": "*Per maggiori info su trend e consigli passa a un piano superiore! 😉*",
            "role1": "*Per maggiori info su trend e consigli passa a un piano superiore! 😉*",
            "role2": "*Per i consigli personalizzati passa al livello successivo! 🧠*",
            "role3": "*Hai sbloccato i consigli personalizzati ✨*",
            "mod": "*Report completo per moderazione.*",
        }
        if profile != "role3":
            note_value = notes_by_profile.get(profile, "")
            if note_value:
                _add_section(embed, name="📌 **NOTE**", value=_with_spacing(note_value))
        embed.set_footer(text="Barcellometro")
        return embed

    class _BarcelloFeedbackView(discord.ui.View):
        def __init__(
            self,
            *,
            database: Any,
            owner_id: int,
            channel_id: str,
            snapshot_id: str,
            score_pred: int,
            profile: str | None,
        ) -> None:
            super().__init__(timeout=600)
            self._database = database
            self._owner_id = owner_id
            self._channel_id = channel_id
            self._snapshot_id = snapshot_id
            self._score_pred = score_pred
            self._profile = profile

        async def _ensure_owner(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self._owner_id:
                await interaction.response.send_message("Feedback riservato ai mod.", ephemeral=True)
                return False
            return True

        async def _store_feedback(
            self,
            *,
            verdict: str,
            reason: str | None,
            delta_target: int | None,
        ) -> None:
            try:
                await self._database.insert_barcello_feedback(
                    created_at=datetime.now(timezone.utc).isoformat(),
                    channel_id=self._channel_id,
                    snapshot_id=self._snapshot_id,
                    rater_user_id=str(self._owner_id),
                    verdict=verdict,
                    reason=reason,
                    delta_target=delta_target,
                    score_pred=self._score_pred,
                    profile=self._profile,
                )
            except Exception:
                logger.exception("Failed to store barcello feedback")

        async def _finalize(self, interaction: discord.Interaction) -> None:
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content="Feedback registrato ✅",
                embeds=interaction.message.embeds,
                view=self,
            )

        @discord.ui.button(label="✅ Accurato", style=discord.ButtonStyle.success)
        async def accurate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
            if not await self._ensure_owner(interaction):
                return
            await self._store_feedback(verdict="accurate", reason=None, delta_target=None)
            await self._finalize(interaction)

        @discord.ui.button(label="❌ Inaccurato", style=discord.ButtonStyle.danger)
        async def inaccurate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
            if not await self._ensure_owner(interaction):
                return
            view = _BarcelloFeedbackSelectView(
                database=self._database,
                owner_id=self._owner_id,
                channel_id=self._channel_id,
                snapshot_id=self._snapshot_id,
                score_pred=self._score_pred,
                profile=self._profile,
            )
            await interaction.response.edit_message(
                content="Seleziona motivo e correzione punteggio.",
                embeds=interaction.message.embeds,
                view=view,
            )

    class _BarcelloFeedbackSelectView(discord.ui.View):
        def __init__(
            self,
            *,
            database: Any,
            owner_id: int,
            channel_id: str,
            snapshot_id: str,
            score_pred: int,
            profile: str | None,
        ) -> None:
            super().__init__(timeout=600)
            self._database = database
            self._owner_id = owner_id
            self._channel_id = channel_id
            self._snapshot_id = snapshot_id
            self._score_pred = score_pred
            self._profile = profile
            self._reason: str | None = None
            self._delta_target: int | None = None

            self.reason_select = discord.ui.Select(
                placeholder="Motivo",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(label="Sarcasmo/ironia scambiato per tensione", value="sarcasmo"),
                    discord.SelectOption(label="Tensione fredda non rilevata", value="tensione_fredda"),
                    discord.SelectOption(label="Duello tra pochi utenti", value="duello_pochi"),
                    discord.SelectOption(label="Picco momentaneo", value="picco_momentaneo"),
                    discord.SelectOption(label="Altro", value="altro"),
                ],
            )
            self.reason_select.callback = self._on_reason_select
            self.add_item(self.reason_select)

            self.delta_select = discord.ui.Select(
                placeholder="Correzione punteggio",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(label="Troppo severo → +10", value="10"),
                    discord.SelectOption(label="Troppo severo → +20", value="20"),
                    discord.SelectOption(label="Troppo severo → +30", value="30"),
                    discord.SelectOption(label="Troppo permissivo → -10", value="-10"),
                    discord.SelectOption(label="Troppo permissivo → -20", value="-20"),
                    discord.SelectOption(label="Troppo permissivo → -30", value="-30"),
                ],
            )
            self.delta_select.callback = self._on_delta_select
            self.add_item(self.delta_select)

        async def _ensure_owner(self, interaction: discord.Interaction) -> bool:
            if interaction.user.id != self._owner_id:
                await interaction.response.send_message("Feedback riservato ai mod.", ephemeral=True)
                return False
            return True

        async def _on_reason_select(self, interaction: discord.Interaction) -> None:
            if not await self._ensure_owner(interaction):
                return
            self._reason = self.reason_select.values[0]
            await interaction.response.defer()

        async def _on_delta_select(self, interaction: discord.Interaction) -> None:
            if not await self._ensure_owner(interaction):
                return
            value = self.delta_select.values[0]
            try:
                self._delta_target = int(value)
            except ValueError:
                self._delta_target = None
            await interaction.response.defer()

        @discord.ui.button(label="Invia feedback", style=discord.ButtonStyle.primary)
        async def submit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
            if not await self._ensure_owner(interaction):
                return
            if not self._reason or self._delta_target is None:
                await interaction.response.send_message("Seleziona motivo e correzione.", ephemeral=True)
                return
            try:
                await self._database.insert_barcello_feedback(
                    created_at=datetime.now(timezone.utc).isoformat(),
                    channel_id=self._channel_id,
                    snapshot_id=self._snapshot_id,
                    rater_user_id=str(self._owner_id),
                    verdict="inaccurate",
                    reason=self._reason,
                    delta_target=self._delta_target,
                    score_pred=self._score_pred,
                    profile=self._profile,
                )
            except Exception:
                logger.exception("Failed to store barcello feedback")
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(
                content="Feedback registrato ✅",
                embeds=interaction.message.embeds,
                view=self,
            )

    def _extract_ai_text(response: Any) -> str:
        output_text = getattr(response, "output_text", "") or ""
        if output_text:
            return output_text
        chunks: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if not text and getattr(content, "type", None) in {"output_text", "text"}:
                    text = getattr(content, "text", "")
                if text:
                    chunks.append(text)
        return "\n".join(chunks).strip()

    def _parse_json_safe(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        raw = text.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
        if "```" in raw:
            start = raw.find("```")
            if start != -1:
                fence_lang_end = raw.find("\n", start + 3)
                if fence_lang_end != -1:
                    end = raw.find("```", fence_lang_end + 1)
                    if end != -1:
                        fenced = raw[fence_lang_end:end].strip()
                        try:
                            parsed = json.loads(fenced)
                            return parsed if isinstance(parsed, dict) else None
                        except json.JSONDecodeError:
                            return None
        start_obj = raw.find("{")
        end_obj = raw.rfind("}")
        if start_obj != -1 and end_obj != -1 and end_obj > start_obj:
            candidate = raw[start_obj : end_obj + 1]
            try:
                parsed = json.loads(candidate)
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None

    async def _call_openai_json(
        client: Any,
        model: str,
        input_payload: list[dict[str, str]],
    ) -> tuple[dict[str, Any] | None, str]:
        try:
            response = await client.responses.create(
                model=model,
                response_format={"type": "json_object"},
                input=input_payload,
            )
            logger.info("OpenAI response_format supported")
        except TypeError as exc:
            if "response_format" not in str(exc):
                raise
            logger.warning("OpenAI response_format unsupported; falling back")
            response = await client.responses.create(
                model=model,
                input=input_payload,
            )
        logger.info("OpenAI response received")
        ai_text = _extract_ai_text(response)
        payload = _parse_json_safe(ai_text)
        return payload, ai_text

    def voice_ingest_key(bot_id: int, key: str) -> str:
        return f"voice_ingest.{bot_id}.{key}"

    async def resolve_voice_channel(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None,
    ) -> discord.VoiceChannel | None:
        if voice_channel is not None:
            return voice_channel
        if isinstance(interaction.user, discord.Member) and interaction.user.voice:
            return interaction.user.voice.channel
        return None

    async def resolve_affected_bots(voice_channel: discord.VoiceChannel) -> list[int]:
        bot_ids = {member.id for member in voice_channel.members if member.bot}
        if not bot_ids:
            bot_ids.update(
                int(bot_id)
                for bot_id in await database.find_voice_ingest_bots_for_voice_channel(str(voice_channel.id))
                if bot_id.isdigit()
            )
        return sorted(bot_ids)

    async def emit_privacy_event(
        interaction: discord.Interaction,
        event_type: str,
        voice_channel: discord.VoiceChannel,
        affected_bot_ids: list[int],
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        await ingest.emit(
            EventEnvelope(
                event_id=str(uuid4()),
                event_type=event_type,
                platform="discord",
                ts=ts,
                guild_id=str(interaction.guild_id) if interaction.guild_id else None,
                channel_id=str(voice_channel.id),
                thread_id=None,
                author_id=str(interaction.user.id),
                content=None,
                meta={"voice_channel_id": str(voice_channel.id), "affected_bot_ids": affected_bot_ids},
            )
        )

    @barcellometro_group.command(name="check", description="Abilita o disabilita la raccolta eventi nel canale")
    @app_commands.describe(state="on/off")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def check_command(interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        if not await check_permission(interaction, "barcellometro.check"):
            return
        if not interaction.channel or not isinstance(interaction.channel, discord.abc.GuildChannel):
            await interaction.response.send_message("Questo comando funziona solo nei canali della guild.", ephemeral=True)
            return
        enabled = 1 if state.value == "on" else 0
        await database.upsert_channel(
            channel_id=str(interaction.channel.id),
            guild_id=str(interaction.guild_id),
            name=interaction.channel.name,
            enabled=enabled,
            channel_type=str(interaction.channel.type),
            category_id=str(interaction.channel.category_id) if interaction.channel.category_id else None,
            is_nsfw=1 if interaction.channel.is_nsfw() else 0,
            slowmode_delay=interaction.channel.slowmode_delay,
        )
        await interaction.response.send_message(
            f"Canale {'abilitato' if enabled else 'disabilitato'} per la raccolta eventi.",
            ephemeral=True,
        )

    @barcellometro_group.command(name="retention", description="Gestisci la retention dei dati")
    @app_commands.describe(action="get/set", days="Numero di giorni di retention")
    @app_commands.choices(action=[app_commands.Choice(name="get", value="get"), app_commands.Choice(name="set", value="set")])
    async def retention_command(
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        days: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.retention"):
            return
        if action.value == "get":
            current = await retention.get_retention_days()
            await interaction.response.send_message(f"Retention attuale: {current} giorni.", ephemeral=True)
            return
        if days is None or days <= 0:
            await interaction.response.send_message("Specifica un numero di giorni valido.", ephemeral=True)
            return
        await retention.set_retention_days(days)
        await interaction.response.send_message(f"Retention aggiornata a {days} giorni.", ephemeral=True)

    @barcellometro_group.command(name="backfill", description="Gestisci il backfill dei dati")
    @app_commands.describe(state="on/off", days="Numero di giorni di backfill")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def backfill_command(
        interaction: discord.Interaction,
        state: app_commands.Choice[str] | None = None,
        days: int | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.backfill"):
            return
        if interaction.response.is_done():
            responder = interaction.followup
        else:
            responder = interaction.response
        if state is None and days is None:
            current_days = await backfill.get_backfill_days()
            enabled = await backfill.is_enabled()
            await responder.send_message(
                f"Backfill {'attivo' if enabled else 'disattivato'} ({current_days} giorni).",
                ephemeral=True,
            )
            return

        if days is not None:
            if days <= 0:
                await responder.send_message("Specifica un numero di giorni valido.", ephemeral=True)
                return
            await backfill.set_backfill_days(days)

        if state is not None:
            await backfill.set_enabled(state.value == "on")

        if await backfill.is_enabled():
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True, thinking=True)
            result = await backfill.run_once(force_full_window=True)
            await interaction.followup.send(
                "Backfill completato. "
                f"Messaggi: {result.messages}, Eventi: {result.events}, Canali: {result.channels}, Errori: {result.errors}.",
                ephemeral=True,
            )
            return

        await responder.send_message("Backfill disattivato.", ephemeral=True)

    @barcellometro_group.command(name="ai", description="Abilita o disabilita il servizio AI")
    @app_commands.describe(state="on/off")
    @app_commands.choices(state=[app_commands.Choice(name="on", value="on"), app_commands.Choice(name="off", value="off")])
    async def ai_command(interaction: discord.Interaction, state: app_commands.Choice[str]) -> None:
        if not await check_permission(interaction, "barcellometro.ai"):
            return
        enabled = state.value == "on"
        await ai_service.set_enabled(enabled)
        await interaction.response.send_message(
            f"AI {'abilitata' if enabled else 'disabilitata'}.",
            ephemeral=True,
        )

    @barcellometro_group.command(name="ai-model", description="Imposta il modello AI per un task")
    @app_commands.describe(task="Task AI", model="Nome modello")
    @app_commands.choices(
        task=[
            app_commands.Choice(name="summary", value="summary"),
            app_commands.Choice(name="transcription", value="transcription"),
            app_commands.Choice(name="translation", value="translation"),
        ]
    )
    async def ai_model_command(
        interaction: discord.Interaction,
        task: app_commands.Choice[str],
        model: str,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.ai-model"):
            return
        await ai_service.set_model(task.value, model)
        await interaction.response.send_message(
            f"Modello per {task.value} aggiornato a {model}.",
            ephemeral=True,
        )

    @stt_group.command(name="backend", description="Imposta il backend STT")
    @app_commands.choices(
        backend=[
            app_commands.Choice(name="local", value="local"),
            app_commands.Choice(name="ai", value="ai"),
        ]
    )
    async def stt_backend_command(
        interaction: discord.Interaction,
        backend: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.backend"):
            return
        await set_setting("stt.backend", backend.value)
        await interaction.response.send_message(f"Backend STT impostato su {backend.value}.", ephemeral=True)

    @stt_group.command(name="model", description="Imposta il modello STT locale")
    @app_commands.choices(
        model=[
            app_commands.Choice(name="small", value="small"),
            app_commands.Choice(name="medium", value="medium"),
            app_commands.Choice(name="large-v3", value="large-v3"),
        ]
    )
    async def stt_model_command(
        interaction: discord.Interaction,
        model: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.model"):
            return
        await set_setting("stt.local.model", model.value)
        await interaction.response.send_message(f"Modello STT impostato su {model.value}.", ephemeral=True)

    @stt_group.command(name="compute", description="Imposta il compute type STT locale")
    @app_commands.choices(
        compute=[
            app_commands.Choice(name="int8", value="int8"),
            app_commands.Choice(name="int8_float16", value="int8_float16"),
            app_commands.Choice(name="float16", value="float16"),
        ]
    )
    async def stt_compute_command(
        interaction: discord.Interaction,
        compute: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.compute"):
            return
        await set_setting("stt.local.compute_type", compute.value)
        await interaction.response.send_message(f"Compute STT impostato su {compute.value}.", ephemeral=True)

    @stt_group.command(name="beam", description="Imposta il beam size STT locale")
    @app_commands.choices(
        beam=[
            app_commands.Choice(name="1", value="1"),
            app_commands.Choice(name="3", value="3"),
            app_commands.Choice(name="5", value="5"),
        ]
    )
    async def stt_beam_command(
        interaction: discord.Interaction,
        beam: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.beam"):
            return
        await set_setting("stt.local.beam_size", beam.value)
        await interaction.response.send_message(f"Beam STT impostato su {beam.value}.", ephemeral=True)

    @stt_group.command(name="language", description="Imposta la lingua STT locale")
    @app_commands.choices(
        language=[
            app_commands.Choice(name="it", value="it"),
            app_commands.Choice(name="auto", value="auto"),
        ]
    )
    async def stt_language_command(
        interaction: discord.Interaction,
        language: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.stt.language"):
            return
        await set_setting("stt.local.language_hint", language.value)
        await interaction.response.send_message(f"Lingua STT impostata su {language.value}.", ephemeral=True)

    @translate_group.command(name="backend", description="Imposta il backend di traduzione")
    @app_commands.choices(
        backend=[
            app_commands.Choice(name="local", value="local"),
            app_commands.Choice(name="ai", value="ai"),
        ]
    )
    async def translate_backend_command(
        interaction: discord.Interaction,
        backend: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.translate.backend"):
            return
        await set_setting("translate.backend", backend.value)
        await interaction.response.send_message(
            f"Backend traduzione impostato su {backend.value}.",
            ephemeral=True,
        )

    @translate_group.command(name="target", description="Imposta la lingua target")
    @app_commands.choices(target=[app_commands.Choice(name="it", value="it")])
    async def translate_target_command(
        interaction: discord.Interaction,
        target: app_commands.Choice[str],
    ) -> None:
        if not await check_permission(interaction, "barcellometro.translate.target"):
            return
        await set_setting("translate.target_lang", target.value)
        await interaction.response.send_message(
            f"Lingua target impostata su {target.value}.",
            ephemeral=True,
        )

    @audio_notes_group.command(name="on", description="Abilita le note vocali")
    async def audio_notes_on_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.on"):
            return
        await set_setting("audio_notes.enabled", "true")
        await interaction.response.send_message("Note vocali abilitate.", ephemeral=True)

    @audio_notes_group.command(name="off", description="Disabilita le note vocali")
    async def audio_notes_off_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.off"):
            return
        await set_setting("audio_notes.enabled", "false")
        await interaction.response.send_message("Note vocali disabilitate.", ephemeral=True)

    @audio_notes_group.command(name="status", description="Mostra lo stato note vocali")
    async def audio_notes_status_command(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.status"):
            return
        enabled = (await get_setting("audio_notes.enabled", "false")).lower() in {"1", "true", "yes", "y"}
        max_mb = await get_setting("audio_notes.max_mb", os.getenv("AUDIO_NOTES_MAX_MB", "25"))
        max_duration = await get_setting("audio_notes.max_duration_s", os.getenv("AUDIO_NOTES_MAX_DURATION_S", "180"))
        max_chars = await get_setting("audio_notes.discord_max_chars", os.getenv("AUDIO_NOTES_DISCORD_MAX_CHARS", "1900"))
        queue_max = await get_setting("audio_notes.queue_max", os.getenv("AUDIO_NOTES_QUEUE_MAX", "50"))
        await interaction.response.send_message(
            "Audio notes "
            f"{'attivo' if enabled else 'disattivo'} | "
            f"max_mb={max_mb}, max_duration_s={max_duration}, max_chars={max_chars}, queue_max={queue_max}",
            ephemeral=True,
        )

    @audio_notes_group.command(name="limits", description="Imposta i limiti note vocali")
    @app_commands.describe(
        max_mb="Massimo MB",
        max_duration_s="Durata massima in secondi",
        discord_max_chars="Massimo caratteri per messaggio",
        queue_max="Dimensione coda",
    )
    async def audio_notes_limits_command(
        interaction: discord.Interaction,
        max_mb: int,
        max_duration_s: int,
        discord_max_chars: int,
        queue_max: int,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.audio_notes.limits"):
            return
        if max_mb <= 0 or max_duration_s <= 0 or discord_max_chars <= 0 or queue_max <= 0:
            await interaction.response.send_message("Specifica limiti validi (> 0).", ephemeral=True)
            return
        await set_setting("audio_notes.max_mb", str(max_mb))
        await set_setting("audio_notes.max_duration_s", str(max_duration_s))
        await set_setting("audio_notes.discord_max_chars", str(discord_max_chars))
        await set_setting("audio_notes.queue_max", str(queue_max))
        await interaction.response.send_message("Limiti note vocali aggiornati.", ephemeral=True)

    @privacy_group.command(name="on", description="Attiva privacy (disconnette il bot dal vocale)")
    @app_commands.describe(voice_channel="Canale vocale (opzionale)")
    async def privacy_on(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.privacy.on"):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await interaction.response.send_message("Specifica un canale vocale.", ephemeral=True)
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await interaction.response.send_message("Nessun bot configurato per questo canale vocale.", ephemeral=True)
            return
        for bot_id in bot_ids:
            await set_setting(voice_ingest_key(bot_id, "privacy_mode"), "true")
            await set_setting(voice_ingest_key(bot_id, "auto_join"), "false")
            await set_setting(voice_ingest_key(bot_id, "enabled"), "true")
        await emit_privacy_event(interaction, "voice.privacy_on", resolved_voice, bot_ids)
        if voice_ingest and bot.user and bot.user.id in bot_ids:
            await voice_ingest.leave()
        await interaction.response.send_message(
            f"Privacy attivata per {resolved_voice.name}. Bot interessati: {len(bot_ids)}.",
            ephemeral=True,
        )

    @privacy_group.command(name="off", description="Disattiva privacy (riabilita auto-join)")
    @app_commands.describe(voice_channel="Canale vocale (opzionale)")
    async def privacy_off(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.privacy.off"):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await interaction.response.send_message("Specifica un canale vocale.", ephemeral=True)
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await interaction.response.send_message("Nessun bot configurato per questo canale vocale.", ephemeral=True)
            return
        for bot_id in bot_ids:
            await set_setting(voice_ingest_key(bot_id, "privacy_mode"), "false")
            await set_setting(voice_ingest_key(bot_id, "auto_join"), "true")
            await set_setting(voice_ingest_key(bot_id, "enabled"), "true")
        await emit_privacy_event(interaction, "voice.privacy_off", resolved_voice, bot_ids)
        non_bot_members = [m for m in resolved_voice.members if not m.bot]
        if voice_ingest and bot.user and bot.user.id in bot_ids and non_bot_members:
            await voice_ingest.join(resolved_voice)
        await interaction.response.send_message(
            f"Privacy disattivata per {resolved_voice.name}. Bot interessati: {len(bot_ids)}.",
            ephemeral=True,
        )

    @privacy_group.command(name="status", description="Mostra lo stato privacy")
    @app_commands.describe(voice_channel="Canale vocale (opzionale)")
    async def privacy_status(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel | None = None,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.privacy.status"):
            return
        resolved_voice = await resolve_voice_channel(interaction, voice_channel)
        if resolved_voice is None:
            await interaction.response.send_message("Specifica un canale vocale.", ephemeral=True)
            return
        bot_ids = await resolve_affected_bots(resolved_voice)
        if not bot_ids:
            await interaction.response.send_message("Nessun bot configurato per questo canale vocale.", ephemeral=True)
            return
        states = []
        for bot_id in bot_ids:
            privacy_mode = (await get_setting(voice_ingest_key(bot_id, "privacy_mode"), "false")).lower() in {"1", "true", "yes", "y"}
            auto_join = (await get_setting(voice_ingest_key(bot_id, "auto_join"), "true")).lower() in {"1", "true", "yes", "y"}
            enabled = (await get_setting(voice_ingest_key(bot_id, "enabled"), "true")).lower() in {"1", "true", "yes", "y"}
            states.append((bot_id, privacy_mode, auto_join, enabled))
        privacy_values = {state[1] for state in states}
        last_event = await database.get_last_privacy_event(str(resolved_voice.id))
        last_change = "N/A"
        if last_event:
            actor = f"<@{last_event['actor_id']}>" if last_event.get("actor_id") else "sconosciuto"
            last_change = f"{last_event['event_type']} alle {last_event['ts']} da {actor}"
        if len(privacy_values) == 1:
            status = "ON" if True in privacy_values else "OFF"
            message = (
                f"Privacy {status} su {resolved_voice.name}. Bot: {len(bot_ids)}. "
                f"Ultimo cambio: {last_change}"
            )
        else:
            lines = [
                f"Bot {bot_id}: privacy={'ON' if privacy else 'OFF'}, auto_join={auto_join}, enabled={enabled}"
                for bot_id, privacy, auto_join, enabled in states
            ]
            message = (
                f"Privacy su {resolved_voice.name} (stati misti):\n"
                + "\n".join(lines)
                + f"\nUltimo cambio: {last_change}"
            )
        await interaction.response.send_message(message, ephemeral=True)

    @voice_ingest_group.command(name="join", description="Join manuale del canale vocale")
    @app_commands.describe(voice_channel="Canale vocale")
    async def voice_ingest_join(
        interaction: discord.Interaction,
        voice_channel: discord.VoiceChannel,
    ) -> None:
        if not await check_permission(interaction, "barcellometro.voice_ingest.join"):
            return
        if not bot.user:
            await interaction.response.send_message("Bot non pronto.", ephemeral=True)
            return
        await set_setting(voice_ingest_key(bot.user.id, "target_voice_channel_id"), str(voice_channel.id))
        await interaction.response.send_message(
            f"Richiesto join su {voice_channel.name}.",
            ephemeral=True,
        )
        if voice_ingest:
            await voice_ingest.join(voice_channel)

    @voice_ingest_group.command(name="leave", description="Leave manuale del canale vocale")
    async def voice_ingest_leave(interaction: discord.Interaction) -> None:
        if not await check_permission(interaction, "barcellometro.voice_ingest.leave"):
            return
        await interaction.response.send_message("Richiesto leave dal canale vocale.", ephemeral=True)
        if voice_ingest:
            await voice_ingest.leave()

    @status_group.command(name="barcellometro", description="Stato generale o di un servizio/plugin")
    @app_commands.describe(service="Nome servizio o plugin")
    async def status_barcellometro(interaction: discord.Interaction, service: str | None = None) -> None:
        if not await check_permission(interaction, "status.barcellometro"):
            return
        if service:
            status = status_service.component_status(service)
            message = (
                f"**{service}**\n"
                f"Active: {status['active']}\n"
                f"State: {status['state']}\n"
                f"Metrics: {status['metrics']}"
            )
            await interaction.response.send_message(message, ephemeral=True)
            return
        general = await status_service.general_status()
        message = (
            "**Barcellometro Status**\n"
            f"Bot: online\n"
            f"DB Path: {general['db_path']}\n"
            f"Retention Days: {general['retention_days']}\n"
            f"Enabled Channels: {general['enabled_channels']}\n"
            f"Users: {general['users_count']}\n"
            f"Messages: {general['messages_count']}\n"
            f"Events: {general['events_count']}\n"
            f"Last Event: {general['last_event_ts']}"
        )
        await interaction.response.send_message(message, ephemeral=True)

    # Settings JSON for /barcello (entitlements.policies):
    # {
    #   "commands": {
    #     "barcello": {
    #       "profiles": {
    #         "<profile>": {
    #           "allowed": true,
    #           "output": {
    #             "show_score": true,
    #             "show_motivation": true,
    #             "show_trend": true,
    #             "show_advice": true,
    #             "show_mod_metrics": false
    #           },
    #           "capabilities": ["analysis.ai_preferred"],
    #           "messages": {
    #             "dm_text": "Serve PLUS.",
    #             "footer_text": "Passa a PRO per il trend."
    #           }
    #         }
    #       }
    #     }
    #   },
    #   "features": {
    #     "ai": { "allowed_profiles": ["role2", "role3", "mod"] }
    #   }
    # }
    @app_commands.command(name="barcello", description="Mostra lo stato del barcello (in DM)")
    @app_commands.rename(window_minutes="minuti")
    @app_commands.describe(window_minutes="Finestra in minuti")
    async def barcello_command(interaction: discord.Interaction, window_minutes: int | None = None) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True, thinking=True)
                logger.info("barcello: deferred")
            except Exception:
                logger.exception("barcello: failed to defer")
        if interaction.guild_id is None or interaction.channel_id is None:
            await send_ephemeral(interaction, "Questo comando funziona solo nei canali della guild.")
            return

        try:
            entitlements_service: EntitlementsService = registry.get("entitlements")
            config = await entitlements_service.get_command_profile_config(interaction.user, "barcello")
            profile, winner_role_id = await entitlements_service.resolve_profile_with_role_id(interaction.user)

            async def try_send_dm(
                content: str | None = None,
                *,
                embed: discord.Embed | None = None,
                embeds: list[discord.Embed] | None = None,
                view: discord.ui.View | None = None,
            ) -> bool:
                try:
                    if embeds is not None:
                        await interaction.user.send(embeds=embeds, view=view)
                    elif embed is not None:
                        await interaction.user.send(embed=embed, view=view)
                    else:
                        await interaction.user.send(content or "")
                    return True
                except discord.Forbidden:
                    return False

            if not config["allowed"]:
                dm_text = config["messages"].get("dm_text", "Serve almeno PLUS per usare /barcello.")
                if await try_send_dm(dm_text):
                    await send_ephemeral(interaction, "Ti ho inviato un DM")
                else:
                    await send_ephemeral(interaction, "Apri i DM per ricevere la risposta")
                return

            if not await check_permission(interaction, "barcello"):
                return

            if window_minutes is None:
                raw_default = await get_setting("barcello.default_window_minutes", "30")
                try:
                    window_minutes = int(raw_default)
                except ValueError:
                    window_minutes = 30
            if window_minutes <= 0:
                window_minutes = 30

            result = await barcello.compute_channel(
                str(interaction.guild_id),
                str(interaction.channel_id),
                window_minutes,
            )

            reasons_text = _format_motivations(result.reasons)
            trend_text = ""
            if result.trend:
                direction = result.trend.get("direction", "stable")
                delta = result.trend.get("delta", 0)
                trend_label = {"stable": "stabile", "improving": "in miglioramento", "worsening": "in peggioramento"}.get(
                    direction,
                    direction,
                )
                trend_text = f"Trend {trend_label} (Δ {delta:+d})."
            advice_candidates = [item.strip() for item in (result.advice or []) if str(item).strip()]
            color_label = (result.color or "nero").lower()
            fallback_personal = _fallback_personal_advice(color_label)
            personal_advice = advice_candidates or fallback_personal
            if len(personal_advice) < 3:
                personal_advice = (personal_advice + fallback_personal)[:3]
            mod_advice = _fallback_mod_advice(color_label)
            ai_note = ""

            if "analysis.ai_preferred" in (config.get("capabilities") or []):
                if registry.has("ai"):
                    ai_enabled = await entitlements_service.is_feature_allowed(interaction.user, "ai")
                    ai_service_enabled = ai_service.is_enabled() if ai_service else False
                    if ai_enabled and ai_service_enabled and ai_service:
                        client = ai_service.client()
                        model = ai_service.get_model("summary")
                        if client and model:
                            try:
                                system_prompt = (
                                    "Scrivi in italiano, tono pratico e calmo (Criceto Mannaro ma non cringe). "
                                    "Non includere nomi utenti, dati sensibili o accuse. "
                                    "Non aggiungere dettagli non presenti. "
                                    "Restituisci SOLO JSON con chiavi: motivation, trend, "
                                    "personal_advice_bullets, mod_advice_bullets. "
                                    "Le liste devono avere 3-5 elementi, massimo 120 caratteri ciascuno. "
                                    "Return ONLY valid JSON. No markdown, no prose."
                                )
                                metrics = result.metrics or {}
                                user_payload = json.dumps(
                                    {
                                        "channel": getattr(interaction.channel, "name", ""),
                                        "window_minutes": window_minutes,
                                        "score": result.score,
                                        "color": result.color,
                                        "trend": result.trend,
                                        "motivations": result.reasons,
                                        "metrics": {
                                            "msg_per_min": metrics.get("msg_per_min"),
                                            "caps_ratio": metrics.get("caps_ratio"),
                                            "mention_per_min": metrics.get("mention_per_min"),
                                            "negativity_hits": metrics.get("negativity_hits"),
                                            "reply_war": metrics.get("reply_war"),
                                        },
                                        "wants_mod_advice": profile == "mod",
                                    },
                                    ensure_ascii=False,
                                )
                                ai_payload, ai_text = await _call_openai_json(
                                    client,
                                    model,
                                    [
                                        {"role": "system", "content": system_prompt},
                                        {"role": "user", "content": user_payload},
                                    ],
                                )
                                if not ai_text:
                                    logger.warning("OpenAI output empty")
                                if ai_payload is None:
                                    snippet = ai_text[:200]
                                    logger.warning("OpenAI output not JSON: %s", snippet)
                                    ai_note = "AI non disponibile: report base."
                                else:
                                    logger.info("AI JSON parsed ok")
                                    reasons_text = _normalize_bullets(ai_payload.get("motivation", reasons_text) or reasons_text)
                                    trend_text = ai_payload.get("trend", trend_text) or trend_text
                                    ai_personal = ai_payload.get("personal_advice_bullets")
                                    ai_mod = ai_payload.get("mod_advice_bullets")
                                    if isinstance(ai_personal, list):
                                        personal_advice = [str(item).strip() for item in ai_personal if str(item).strip()]
                                    if isinstance(ai_mod, list):
                                        mod_advice = [str(item).strip() for item in ai_mod if str(item).strip()]
                                    if len(personal_advice) < 3:
                                        personal_advice = (personal_advice + fallback_personal)[:3]
                                    if len(mod_advice) < 3:
                                        mod_advice = (mod_advice + _fallback_mod_advice(color_label))[:3]
                            except Exception:  # noqa: BLE001
                                logger.exception("AI barcello enrichment failed")
                                ai_note = "AI non disponibile: report base."

            output_flags = config.get("output", {})
            public_embed = _build_barcello_public_embed(
                result=result,
                channel_name=getattr(interaction.channel, "name", ""),
                window_minutes=window_minutes,
            )
            details_color = await _get_details_embed_color(profile)
            tier_display_name = await _resolve_tier_display_name(
                profile=profile,
                winner_role_id=winner_role_id,
                guild=interaction.guild,
            )
            details_embed = _build_barcello_details_embed(
                result=result,
                output_flags=output_flags,
                profile=profile,
                tier_display_name=tier_display_name,
                embed_color=details_color,
                reasons_text=reasons_text,
                trend_text=trend_text,
                personal_advice=personal_advice,
                mod_advice=mod_advice,
                ai_note=ai_note,
            )
            feedback_view = None
            if profile == "mod":
                snapshot_id = f"{interaction.channel_id}:{result.window_start_ts}:{result.window_end_ts}"
                feedback_view = _BarcelloFeedbackView(
                    database=database,
                    owner_id=interaction.user.id,
                    channel_id=str(interaction.channel_id),
                    snapshot_id=snapshot_id,
                    score_pred=result.score,
                    profile=profile,
                )

            if await try_send_dm(embeds=[public_embed, details_embed], view=feedback_view):
                await interaction.followup.send("Ti ho inviato un DM", ephemeral=True)
            else:
                await interaction.followup.send(
                    "Non riesco a inviarti DM (privacy). Abilita i messaggi privati dal server.",
                    ephemeral=True,
                )
        except Exception:
            logger.exception("barcello: unexpected error")
            await interaction.followup.send("Errore temporaneo, riprova.", ephemeral=True)

    bot.tree.add_command(barcellometro_group, guild=guild)
    bot.tree.add_command(status_group, guild=guild)
    bot.tree.add_command(privacy_group, guild=guild)
    bot.tree.add_command(barcello_command, guild=guild)

    @role_group.command(name="set-role", description="Imposta limiti per un ruolo su un comando")
    @app_commands.describe(role="Ruolo", command="Nome comando", usage_limit="Limite utilizzi (vuoto = illimitato)", cooldown_seconds="Cooldown in secondi")
    async def role_set_command(
        interaction: discord.Interaction,
        role: discord.Role,
        command: str,
        usage_limit: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        if usage_limit is not None and usage_limit <= 0:
            await interaction.response.send_message("Specifica un limite utilizzi valido.", ephemeral=True)
            return
        if cooldown_seconds is not None and cooldown_seconds < 0:
            await interaction.response.send_message("Specifica un cooldown valido.", ephemeral=True)
            return
        await database.upsert_role_policy(
            guild_id=str(interaction.guild_id),
            role_id=str(role.id),
            command=command,
            usage_limit=usage_limit,
            cooldown_seconds=cooldown_seconds,
        )
        await interaction.response.send_message("Policy ruolo aggiornata.", ephemeral=True)

    @role_group.command(name="set-user", description="Imposta limiti per un utente su un comando")
    @app_commands.describe(user="Utente", command="Nome comando", usage_limit="Limite utilizzi (vuoto = illimitato)", cooldown_seconds="Cooldown in secondi")
    async def user_set_command(
        interaction: discord.Interaction,
        user: discord.User,
        command: str,
        usage_limit: int | None = None,
        cooldown_seconds: int | None = None,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        if usage_limit is not None and usage_limit <= 0:
            await interaction.response.send_message("Specifica un limite utilizzi valido.", ephemeral=True)
            return
        if cooldown_seconds is not None and cooldown_seconds < 0:
            await interaction.response.send_message("Specifica un cooldown valido.", ephemeral=True)
            return
        await database.upsert_user_policy(
            guild_id=str(interaction.guild_id),
            user_id=str(user.id),
            command=command,
            usage_limit=usage_limit,
            cooldown_seconds=cooldown_seconds,
        )
        await interaction.response.send_message("Policy utente aggiornata.", ephemeral=True)

    @role_group.command(name="clear-role", description="Rimuove la policy di un ruolo")
    @app_commands.describe(role="Ruolo", command="Nome comando")
    async def role_clear_command(
        interaction: discord.Interaction,
        role: discord.Role,
        command: str,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        await database.delete_role_policy(
            guild_id=str(interaction.guild_id),
            role_id=str(role.id),
            command=command,
        )
        await interaction.response.send_message("Policy ruolo rimossa.", ephemeral=True)

    @role_group.command(name="clear-user", description="Rimuove la policy di un utente")
    @app_commands.describe(user="Utente", command="Nome comando")
    async def user_clear_command(
        interaction: discord.Interaction,
        user: discord.User,
        command: str,
    ) -> None:
        if not await ensure_admin(interaction):
            return
        await database.delete_user_policy(
            guild_id=str(interaction.guild_id),
            user_id=str(user.id),
            command=command,
        )
        await interaction.response.send_message("Policy utente rimossa.", ephemeral=True)

    @role_group.command(name="show-role", description="Mostra le policy di un ruolo")
    @app_commands.describe(role="Ruolo")
    async def role_show_command(interaction: discord.Interaction, role: discord.Role) -> None:
        if not await ensure_admin(interaction):
            return
        rows = await database.fetch_role_policies(str(interaction.guild_id), str(role.id))
        if not rows:
            await interaction.response.send_message("Nessuna policy per questo ruolo.", ephemeral=True)
            return
        lines = []
        for row in rows:
            limit = row["usage_limit"] if row["usage_limit"] is not None else "∞"
            cooldown = row["cooldown_seconds"] if row["cooldown_seconds"] is not None else "∞"
            lines.append(f"{row['command']}: limit={limit} cooldown={cooldown}")
        await interaction.response.send_message("\\n".join(lines), ephemeral=True)

    @role_group.command(name="show-user", description="Mostra le policy di un utente")
    @app_commands.describe(user="Utente")
    async def user_show_command(interaction: discord.Interaction, user: discord.User) -> None:
        if not await ensure_admin(interaction):
            return
        rows = await database.fetch_user_policies(str(interaction.guild_id), str(user.id))
        if not rows:
            await interaction.response.send_message("Nessuna policy per questo utente.", ephemeral=True)
            return
        lines = []
        for row in rows:
            limit = row["usage_limit"] if row["usage_limit"] is not None else "∞"
            cooldown = row["cooldown_seconds"] if row["cooldown_seconds"] is not None else "∞"
            lines.append(f"{row['command']}: limit={limit} cooldown={cooldown}")
        await interaction.response.send_message("\\n".join(lines), ephemeral=True)

    async def handle_ready() -> None:
        try:
            synced = await bot.tree.sync(guild=guild)
            logger.info("Synced %s commands for guild %s", len(synced), config.guild_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to sync commands")

    bot.add_listener(handle_ready, "on_ready")
