from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord

from app.services.barcello import BarcelloService
from app.services.database import DatabaseService
from app.services.summary import SummaryService
from app.utils.summary_render import build_summary_detail_embeds

logger = logging.getLogger(__name__)
ROME_TZ = ZoneInfo("Europe/Rome")
DUE_WINDOW_SECONDS = 90


class DailyResocontoService:
    def __init__(
        self,
        database: DatabaseService,
        bot: discord.Client,
        summary_service: SummaryService,
        barcello_service: BarcelloService,
        ai_service: object | None = None,
    ) -> None:
        self._database = database
        self._bot = bot
        self._summary = summary_service
        self._barcello = barcello_service
        self._ai = ai_service
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        await self._bot.wait_until_ready()
        while True:
            try:
                await self.run_once()
            except Exception:
                logger.exception("daily_resoconto tick failed")
            await asyncio.sleep(30)

    async def run_once(self) -> None:
        now_utc = datetime.now(timezone.utc)
        now_local = now_utc.astimezone(ROME_TZ)
        for guild in self._bot.guilds:
            rows = await self._database.list_enabled_daily_report_channels(str(guild.id))
            for row in rows:
                channel_id = str(row["channel_id"])
                today = now_local.date().isoformat()
                if row["last_sent_local_date"] == today:
                    logger.info("daily_resoconto skip channel=%s reason=already_sent", channel_id)
                    continue
                try:
                    hh, mm = str(row["send_time_local"]).split(":", 1)
                    send_local = now_local.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                except Exception:
                    logger.warning("daily_resoconto skip channel=%s reason=invalid_time_format", channel_id)
                    continue
                delta_seconds = (now_local - send_local).total_seconds()
                if delta_seconds < 0:
                    logger.info("daily_resoconto skip channel=%s reason=not_due_yet", channel_id)
                    continue
                if delta_seconds > DUE_WINDOW_SECONDS:
                    logger.info(
                        "daily_resoconto skip channel=%s reason=missed_window delta=%.0fs",
                        channel_id,
                        delta_seconds,
                    )
                    continue
                sent = await self.generate_and_send_for_channel(str(guild.id), channel_id, manual=False)
                if sent:
                    await self._database.mark_daily_report_sent(str(guild.id), channel_id, today)
                    logger.info("daily_resoconto sent ok guild=%s channel=%s", guild.id, channel_id)

    async def generate_and_send_for_channel(self, guild_id: str, channel_id: str, *, manual: bool = False) -> bool:
        channel = self._bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.abc.Messageable):
            logger.warning("daily_resoconto channel not accessible guild=%s channel=%s", guild_id, channel_id)
            return False

        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(hours=24)
        rows = await self._database.fetch_messages_in_range(
            channel_id=channel_id,
            start_ts=start_dt.isoformat(),
            end_ts=end_dt.isoformat(),
            limit=1200,
        )
        messages = [
            {
                "ts": row["ts"],
                "author_id": str(row["author_id"] or "") or None,
                "content": str(row["content"] or ""),
                "message_id": str(row["message_id"] or "") or None,
                "meta": {"kind": "chat", "in_call": False},
            }
            for row in rows
            if str(row["content"] or "").strip()
        ]

        bar = await self._barcello.compute_channel(guild_id, channel_id, 1440, now_ts=end_dt.isoformat())
        config = await self._summary.get_config()
        ai_allowed = bool(self._ai and getattr(self._ai, "is_enabled", lambda: False)())
        summary = await self._summary.build_summary(
            guild_id=guild_id,
            channel_id=channel_id,
            start_ts=start_dt.isoformat(),
            end_ts=end_dt.isoformat(),
            tier="role3",
            include_names=False,
            ai_allowed=ai_allowed,
            evidence_mode=False,
            voice_context=False,
            config=config,
            barcello_metrics=bar.metrics,
            max_message_ts=messages[-1]["ts"] if messages else None,
            messages=messages,
            granularity_hint="days",
            summary_mode="daily_report",
        )

        period_desc = await self._summary.build_period_description(
            tier="role3",
            period_prefix="Nelle ultime 24 ore",
            score=bar.score,
            color=bar.color,
            metrics=bar.metrics,
            trend=bar.trend,
            ai_allowed=ai_allowed,
            config=config,
        )
        period_desc = period_desc or ""
        tones = self._build_tone_line(bar.metrics)
        advice, proverbio = await self._get_advice_proverbio(summary, bar.color)

        emoji = {"verde": "🟢", "giallo": "🟡", "rosso": "🔴", "nero": "⚫"}.get(bar.color, "⚫")
        alert = {
            "verde": "È un buon momento per scrivere e partecipare 💬",
            "giallo": "Clima un po’ teso: scrivi con calma e chiarisci se serve 🙂",
            "rosso": "Tensione alta: evita provocazioni e abbassa i toni 🧯",
            "nero": "Situazione critica: meglio fermarsi e moderare subito 🚨",
        }.get(bar.color, "Situazione critica: meglio fermarsi e moderare subito 🚨")
        status_embed = discord.Embed(
            title="📊 RESOCONTO GIORNALIERO — PRO MAX",
            description=f"🕒 **Ultime 24 ore**\n\n**{emoji} ALLERTA {bar.color.upper()}**\n{alert}\n{tones}",
            color={"verde": 0x2ECC71, "giallo": 0xF1C40F, "rosso": 0xE74C3C, "nero": 0x2F3136}.get(bar.color, 0x2F3136),
        )
        status_embed.add_field(
            name="🫀 PUNTI SALUTE",
            value=f"{bar.score}/100" + (f"\n{period_desc}" if period_desc else ""),
            inline=False,
        )
        status_embed.set_footer(text="Barcellometro")

        details = build_summary_detail_embeds(
            profile="role3",
            summary=summary,
            include_names=False,
            include_date_in_time=False,
            guild_id=int(guild_id),
            channel_id=int(channel_id),
            name_map={},
            moment_primary={},
            quote_primary={},
            dynamic_primary={},
            impact_primary={},
            moment_display={},
            quote_display={},
            dynamic_names={},
            quote_texts={},
            privacy_intervals=None,
            privacy_disclaimer_lines=None,
            metrics_report=None,
            extra_sections=[
                ("🧭 I CONSIGLI DEL BARCELLOMETRO", "\n".join(f"• {x}" for x in advice), 3),
                ("🍀 PROVERBIO DEL GIORNO", proverbio, 3),
            ],
            tier_label="PRO MAX",
            tier_config=config["tiers"]["role3"],
            details_color=0x95A5A6,
            req_id="daily",
            format_moment_line=lambda **kw: kw["moment"].text,
            format_quote_line=lambda **kw: f'“{kw["quote"].text}”',
            format_dynamic_line=lambda **kw: kw["dynamic"].text,
            format_impact_line=lambda **kw: kw["impact"].reason,
            format_bullets=lambda lines: "\n".join(f"• {ln}" for ln in lines if str(ln).strip()),
        )

        await channel.send(embeds=[status_embed, *details[:1]])
        if manual:
            today = datetime.now(ROME_TZ).date().isoformat()
            await self._database.mark_daily_report_sent(guild_id, channel_id, today)
        logger.info("daily_resoconto sent guild=%s channel=%s manual=%s", guild_id, channel_id, manual)
        return True

    def _build_tone_line(self, metrics: dict[str, object]) -> str:
        negativity_hits = int(metrics.get("negativity_hits") or 0)
        positive_hits = int(metrics.get("positive_hits") or 0)
        questions = int(metrics.get("questions") or 0)
        if negativity_hits > 0:
            return "Analisi toni del giorno: tono con tensione e bisogno di chiarimenti 🧯"
        if positive_hits > 0:
            return "Analisi toni del giorno: tono collaborativo e scambi costruttivi 🌿"
        if questions > 1:
            return "Analisi toni del giorno: giornata ricca di domande e chiarimenti ❓"
        return "Analisi toni del giorno: scambi regolari e ritmo stabile 🌤️"

    async def _get_advice_proverbio(self, summary: object, color: str) -> tuple[list[str], str]:
        if self._ai and getattr(self._ai, "is_enabled", lambda: False)() and getattr(self._ai, "client", lambda: None)():
            try:
                client = self._ai.client()
                model = self._ai.get_model("summary") or "gpt-4o-mini"
                payload = {"color": color, "themes": getattr(summary, "themes", []), "moments": [m.text for m in getattr(summary, "moments", [])[:4]]}
                response = await client.responses.create(
                    model=model,
                    response_format={"type": "json_object"},
                    input=[
                        {"role": "system", "content": "Restituisci SOLO JSON con advice_bullets (3-5) e proverbio (1 riga). Italiano."},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                )
                text = getattr(response, "output_text", "") or "{}"
                data = json.loads(text)
                advice = [str(x).strip() for x in data.get("advice_bullets", []) if str(x).strip()][:5]
                proverbio = str(data.get("proverbio") or "").strip()
                if advice and proverbio:
                    return advice, proverbio
            except Exception:
                logger.exception("daily_resoconto advice ai failed")
        fallback = {
            "verde": (["Mantieni il tono positivo e ringrazia chi aiuta.", "Conferma i prossimi passi in modo chiaro.", "Premia i contributi costruttivi del canale."], "Chi semina bene, raccoglie meglio."),
            "giallo": (["Evita messaggi impulsivi e usa frasi brevi.", "Fai una domanda chiarificatrice prima di rispondere.", "Ricapitola i punti in disaccordo senza accuse."], "Meglio una parola in meno che una di troppo."),
            "rosso": (["Sospendi i thread accesi per qualche minuto.", "Passa da accuse a fatti verificabili.", "Coinvolgi un moderatore se il tono non cala."], "Quando il ferro è caldo, la calma vale oro."),
        }
        return fallback.get(color, (["Fermati, respira e chiarisci l'obiettivo comune.", "Riduci sarcasmo e giudizi personali.", "Riparti da regole semplici di convivenza."], "Dopo la tempesta, torna il sereno."))
