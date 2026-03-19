from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import discord

from app.core.config_paths import AURA_ARCHETYPES_JSON, AURA_MISSIONS_JSON
from app.services.footer import attach_footer_meta

from app.services.aura_archetypes import build_dynamic_archetype_reason
from app.services.config_file_loader import load_json_file
from app.utils.embed_limits import MAX_EMBED_CHARS, _ensure_embed_limits, _estimate_embed_size, _split_field_chunks

logger = logging.getLogger(__name__)
AURA_DETAILS_INTERNAL_BUDGET = 5700


DEFAULT_ARCHETYPE_DEFS: dict[str, dict[str, Any]] = {
    "scintilla": {"label": "Scintilla", "emoji": "✨", "description": "Accendi facilmente il ritmo delle conversazioni.", "profile_reason_template": "Nel periodo hai spesso dato il via ai momenti più vivi della community.", "advice": ["Usa questa energia per coinvolgere anche chi parla meno."], "order": 10, "enabled": True},
    "pacificatore": {"label": "Pacificatore", "emoji": "🌿", "description": "Favorisci toni costruttivi e abbassi gli attriti.", "profile_reason_template": "Hai mantenuto un tono costruttivo e un impatto equilibrato nel clima della community.", "advice": ["Continua a riequilibrare i momenti più tesi senza spegnere il confronto."], "order": 20, "enabled": True},
    "agitatore": {"label": "Agitatore", "emoji": "🔥", "description": "Spingi il ritmo e alzi l'intensità della discussione.", "profile_reason_template": "Hai spinto il ritmo e mosso fortemente l'intensità delle discussioni.", "advice": ["Canalizza l'energia evitando escalation nei momenti delicati."], "order": 30, "enabled": True},
    "collante": {"label": "Collante", "emoji": "🧩", "description": "Tieni insieme persone e conversazioni in più spazi.", "profile_reason_template": "Ti sei mosso tra persone diverse aiutando a tenere vivo il legame nella community.", "advice": ["Continua a fare da ponte tra gruppi e canali diversi."], "order": 40, "enabled": True},
    "mediatore": {"label": "Mediatore", "emoji": "⚖️", "description": "Riequilibri i confronti e faciliti il dialogo.", "profile_reason_template": "Hai facilitato il dialogo smorzando attriti e favorendo confronto equilibrato.", "advice": ["Rendi ancora più esplicita la tua mediazione nei thread tesi."], "order": 50, "enabled": True},
    "esploratore_sociale": {"label": "Esploratore sociale", "emoji": "🧭", "description": "Interagisci con persone diverse in più canali.", "profile_reason_template": "Hai attraversato contesti e persone diverse portando varietà alle interazioni.", "advice": ["Mantieni questa varietà e includi anche canali meno attivi."], "order": 60, "enabled": True},
    "costante": {"label": "Costante", "emoji": "⏱️", "description": "Sei presente con regolarità nel tempo.", "profile_reason_template": "Hai mantenuto una presenza stabile e continua senza grandi sbalzi.", "advice": ["Conserva la regolarità aggiungendo piccoli momenti di iniziativa."], "order": 70, "enabled": True},
    "lampo": {"label": "Lampo", "emoji": "⚡", "description": "Intervieni poco ma lasci un impatto netto.", "profile_reason_template": "Anche con presenza ridotta, i tuoi interventi hanno lasciato un impatto evidente.", "advice": ["Quando entri, prova ad attivare anche follow-up leggeri."], "order": 80, "enabled": True},
    "silenzioso": {"label": "Silenzioso", "emoji": "🌙", "description": "Osservi molto e intervieni in modo misurato.", "profile_reason_template": "Hai partecipato in modo discreto e misurato, senza essere assente.", "advice": ["Inserisci qualche intervento in più nei momenti utili."], "order": 90, "enabled": True},
    "ascoltatore": {"label": "Ascoltatore", "emoji": "👂", "description": "Favorisci ascolto e risposte calme.", "profile_reason_template": "Hai sostenuto il dialogo con risposte attente e presenza calma.", "advice": ["Continua con risposte utili, aprendo spazio anche ad altri."], "order": 100, "enabled": True},
    "selettivo": {"label": "Selettivo", "emoji": "🎯", "description": "Concentri le interazioni su pochi contesti mirati.", "profile_reason_template": "Hai concentrato le interazioni su persone e spazi mirati con buona coerenza.", "advice": ["Ogni tanto allarga il raggio per aumentare la diversità."], "order": 110, "enabled": True},
    "dominante": {"label": "Dominante", "emoji": "🦁", "description": "Occupi molto spazio conversazionale e ne dirigi il ritmo.", "profile_reason_template": "Hai occupato una parte importante dello spazio conversazionale del periodo.", "advice": ["Lascia più spazio alle altre voci per migliorare l'equilibrio."], "order": 120, "enabled": True},
}


def _load_archetype_definitions() -> dict[str, dict[str, Any]]:
    cfg = load_json_file(AURA_ARCHETYPES_JSON) or {}
    configured = cfg.get("archetypes", {}) if isinstance(cfg, dict) else {}
    merged = {k: dict(v) for k, v in DEFAULT_ARCHETYPE_DEFS.items()}
    if isinstance(configured, dict):
        for key, value in configured.items():
            if not isinstance(value, dict):
                continue
            base = dict(merged.get(str(key), {}))
            base.update(value)
            merged[str(key)] = base
    return merged


@dataclass
class AuraTrendInfo:
    server_direction: str
    server_comment: str
    channel_direction: str
    channel_comment: str
    server_delta: int
    channel_delta: int


@dataclass
class AuraRenderPayload:
    username: str
    server_name: str
    channel_name: str
    period_line: str
    karma_server_percent: int
    karma_channel_percent: int
    server_points_total: int
    channel_points_month: int
    metrics_json: str
    channel_metrics_json: str
    ledger: list[dict[str, int | str]]
    archetype_metrics: dict[str, object]
    trend: AuraTrendInfo
    assigned_missions: list[dict[str, Any]] | None = None
    points_timeline_lines: list[str] | None = None


def render_karma_bar(percent: int) -> str:
    value = max(0, min(100, int(percent)))
    normalized = value / 100
    segments = ["━"] * 12
    marker_idx = round(normalized * (len(segments) - 1))

    marker = "🟡"
    if normalized < 0.4:
        marker = "🔴"
    elif normalized > 0.6:
        marker = "🟢"

    segments[marker_idx] = marker
    return f"😈{''.join(segments)}😇"


def _direction_label(direction: str) -> str:
    mapping = {
        "improving": "in miglioramento",
        "stable": "stabile",
        "worsening": "in peggioramento",
    }
    return mapping.get(direction, "stabile")


def _compact_bullets(lines: list[str], *, fallback: str) -> str:
    clean = [str(line).strip() for line in lines if str(line).strip()]
    if not clean:
        return f"• {fallback}"
    return "\n".join(f"• {line}" for line in clean)


def _score_lines(ledger_lines: list[str]) -> list[str]:
    if not ledger_lines:
        return ["Nessun dato rilevante nel periodo."]
    if len(ledger_lines) <= 10:
        return ledger_lines
    return ledger_lines[:10]


def _build_main_aura_description(*, aura_payload: AuraRenderPayload) -> str:
    return "\n\n".join(
        [
            f"**🕒 {aura_payload.period_line}**",
            (
                f"**✨ KARMA \"{aura_payload.server_name}\"**\n"
                f"{render_karma_bar(aura_payload.karma_server_percent)}\n\n"
                f"PUNTI AURA TOTALI: **{aura_payload.server_points_total}**"
            ),
            (
                f"**✨ KARMA \"{aura_payload.channel_name}\"**\n"
                f"{render_karma_bar(aura_payload.karma_channel_percent)}\n\n"
                f"PUNTI AURA CANALE: **{aura_payload.channel_points_month}**"
            ),
            (
                "📈 TREND\n"
                f"• Nel server in generale: {_direction_label(aura_payload.trend.server_direction)}. {aura_payload.trend.server_comment}\n"
                f"• Nel \"{aura_payload.channel_name}\": {_direction_label(aura_payload.trend.channel_direction)}. {aura_payload.trend.channel_comment}"
            ),
        ]
    )


def _build_missions(metrics: dict[str, Any], archetype_metrics: dict[str, Any], assigned: list[dict[str, Any]] | None = None) -> list[str]:
    cfg = load_json_file(AURA_MISSIONS_JSON) or {}
    if assigned:
        pending: list[dict[str, Any]] = []
        completed: list[dict[str, Any]] = []
        expired: list[dict[str, Any]] = []
        for item in assigned:
            status = str(item.get("status", "assigned")).lower()
            if status == "completed":
                completed.append(item)
            elif status in {"expired", "scaduta", "scaduto"}:
                expired.append(item)
            else:
                pending.append(item)

        lines: list[str] = []
        for item in [*pending, *completed, *expired][:3]:
            label = str(item.get("meta", {}).get("label") or item.get("mission_id") or "missione")
            reward = int(item.get("reward_points", 0) or 0)
            status = str(item.get("status", "assigned")).lower()
            if status == "completed":
                box = "✅"
            elif status in {"expired", "scaduta", "scaduto"}:
                box = "⌛"
            else:
                box = "⬜"
            text = f"{box} {label} (+{reward} P.A.)" if reward > 0 else f"{box} {label}"
            if status == "completed":
                text = f"**{text}**"
            lines.append(text)
        return lines or ["Nessuna per oggi."]
    mission_defs = cfg.get("missions", []) if isinstance(cfg, dict) else []
    msg_count = int(metrics.get("msg_count", 0) or 0)
    unique = int(metrics.get("unique_interactions", 0) or 0)
    degrade = int(metrics.get("degrade_events", 0) or 0)
    scores = archetype_metrics.get("scores", {}) if isinstance(archetype_metrics, dict) else {}
    diversity = int(scores.get("diversity", 0) or 0) if isinstance(scores, dict) else 0
    if msg_count < 3:
        return ["Nessuna per oggi."]

    missions: list[str] = []
    if isinstance(mission_defs, list) and mission_defs:
        for item in mission_defs:
            if not isinstance(item, dict) or not bool(item.get("enabled", True)):
                continue
            text = str(item.get("text", "")).strip()
            reward = int(item.get("bonus_points", 0) or 0)
            cond = str(item.get("condition", "always")).strip().lower()
            ok = cond == "always"
            if cond == "low_diversity":
                ok = unique < 2 or diversity < 40
            elif cond == "high_activity":
                ok = msg_count >= 8 and degrade <= 0
            elif cond == "tension":
                ok = degrade > 0
            if ok and text:
                missions.append(f"⬜ {text} (+{reward} P.A.)" if reward > 0 else f"⬜ {text}")
            if len(missions) >= int(cfg.get("max_per_day", 3) or 3):
                break
    if not missions:
        if unique < 2 or diversity < 40:
            missions.append("⬜ Scrivi un messaggio a qualcuno che non contatti di solito. (+5 P.A.)")
        if msg_count >= 2 and unique <= 3:
            missions.append("⬜ Scrivi 2 messaggi a una persona alla quale non hai mai scritto. (+10 P.A.)")
        if degrade > 0:
            missions.append("⬜ Prova a rispondere con tono calmo in una conversazione accesa. (+10 P.A.)")
        if msg_count >= 8 and degrade <= 0:
            missions.append("**✅ Dai il buongiorno per prima.**")
    return missions[:3] if missions else ["Nessuna per oggi."]


def _resolve_profile_payload(archetype_metrics: dict[str, Any], *, fallback_metrics: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, int], dict[str, Any], dict[str, Any]]:
    profile_defs = _load_archetype_definitions()
    scores = archetype_metrics.get("scores", {}) if isinstance(archetype_metrics, dict) else {}
    payload_metrics = archetype_metrics.get("metrics", {}) if isinstance(archetype_metrics, dict) else {}
    reasons = archetype_metrics.get("reasons", {}) if isinstance(archetype_metrics, dict) else {}

    normalized_scores: dict[str, int] = {}
    if isinstance(scores, dict):
        for key, value in scores.items():
            try:
                normalized_scores[str(key)] = max(0, int(round(float(value))))
            except (TypeError, ValueError):
                continue

    resolved_metrics = dict(fallback_metrics)
    if isinstance(payload_metrics, dict):
        resolved_metrics.update(payload_metrics)

    return profile_defs, normalized_scores, resolved_metrics, reasons if isinstance(reasons, dict) else {}


def _select_top_profile_archetypes(normalized_scores: dict[str, int], profile_defs: dict[str, dict[str, Any]]) -> list[tuple[str, int]]:
    ordered = sorted(
        (
            (key, val)
            for key, val in normalized_scores.items()
            if bool(profile_defs.get(key, {}).get("enabled", True))
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    if not ordered:
        return []

    top = ordered[:2]
    if len(ordered) >= 3 and ordered[2][1] > 0 and (ordered[1][1] - ordered[2][1]) <= 8:
        top.append(ordered[2])
    return top


def _build_profile_traits_lines(archetype_metrics: dict[str, Any], *, fallback_metrics: dict[str, Any]) -> list[str]:
    profile_defs, normalized_scores, resolved_metrics, reasons = _resolve_profile_payload(archetype_metrics, fallback_metrics=fallback_metrics)

    if not normalized_scores:
        climate = max(0, min(100, 50 + (int(fallback_metrics.get("invigorate_events", 0) or 0) - int(fallback_metrics.get("degrade_events", 0) or 0)) * 10))
        return [
            f"• 🔥 **{climate}% Agitatore** — Nel periodo hai avuto diversi momenti intensi.",
            f"• 🌿 **{100 - climate}% Pacificatore** — Hai anche segnali di dialogo costruttivo.",
        ]

    top = _select_top_profile_archetypes(normalized_scores, profile_defs)
    if not top:
        return ["• Nessun dato rilevante nel periodo."]

    lines: list[str] = []
    for archetype_key, pct in top:
        cfg = profile_defs.get(archetype_key, {})
        emoji = str(cfg.get("emoji", "✨")).strip() or "✨"
        label = str(cfg.get("label", archetype_key.replace("_", " ").title())).strip() or archetype_key
        reason = build_dynamic_archetype_reason(
            archetype_key,
            metrics=resolved_metrics,
            scores=normalized_scores,
            config=cfg,
        )

        if reasons.get(archetype_key):
            reason = str(reasons.get(archetype_key)).strip() or reason

        reason = reason[:1].upper() + reason[1:] if reason else "Profilo emerso dalle tue metriche del periodo."
        if not reason.endswith((".", "!", "?")):
            reason = f"{reason}."
        lines.append(f"• {emoji} **{pct}% {label}** — {reason}")
    return lines


def _build_profile_character_analysis_lines(archetype_metrics: dict[str, Any], *, fallback_metrics: dict[str, Any]) -> list[str]:
    profile_defs, normalized_scores, metrics, _ = _resolve_profile_payload(archetype_metrics, fallback_metrics=fallback_metrics)
    top = _select_top_profile_archetypes(normalized_scores, profile_defs)

    msg = int(metrics.get("msg_count", 0) or 0)
    unique = int(metrics.get("unique_interactions", 0) or 0)
    channels = int(metrics.get("channel_diversity", 0) or 0)
    active_days = int(metrics.get("active_days", 0) or 0)
    replies_sent = int(metrics.get("replies_sent", 0) or 0)
    quality = int(metrics.get("quality_counter", 0) or 0)

    if msg <= 0:
        return ["• Dati ancora limitati: continua a partecipare per ottenere un profilo personale più preciso."]

    key1 = top[0][0] if top else ""
    key2 = top[1][0] if len(top) > 1 else ""
    label1 = str(profile_defs.get(key1, {}).get("label", key1.replace("_", " ").title())).strip() if key1 else "profilo"
    label2 = str(profile_defs.get(key2, {}).get("label", key2.replace("_", " ").title())).strip() if key2 else ""

    lines: list[str] = []
    if key1 == "dominante":
        lines.append("• Hai una presenza forte e visibile: occupi spazio nelle conversazioni e ne influenzi spesso il ritmo.")
    elif key1 in {"collante", "esploratore_sociale"}:
        lines.append("• Il tuo profilo appare sociale e distributivo: coinvolgi persone diverse e ti muovi tra più contesti.")
    elif key1 == "costante":
        lines.append("• Hai una presenza regolare e misurata, più orientata alla continuità che al protagonismo.")
    elif key1 == "ascoltatore":
        lines.append("• Ti distingui per interventi mirati e poco invasivi, con attenzione alla qualità dello scambio.")
    elif label1:
        lines.append(f"• Nel periodo emerge soprattutto il tuo lato {label1.lower()}, con segnali abbastanza stabili.")

    if key2 and key2 != key1:
        lines.append(f"• In parallelo compare anche una componente {label2.lower()}, che bilancia il tuo stile principale.")

    if unique >= 10 and channels >= 4:
        lines.append("• Mostri una buona varietà relazionale: la tua presenza non resta bloccata su pochi canali o pochi utenti.")
    elif replies_sent >= max(3, msg // 4) and quality >= 2:
        lines.append("• C'è una componente dialogica chiara: rispondi con continuità e mantieni toni utili nel confronto.")
    elif active_days >= 12:
        lines.append("• La frequenza su molti giorni suggerisce affidabilità e continuità nella partecipazione.")

    return lines[:3] if lines else ["• Profilo in evoluzione: con più interazioni emergeranno pattern più definiti."]


def _build_profile_section_text(archetype_metrics: dict[str, Any], *, fallback_metrics: dict[str, Any]) -> str:
    trait_lines = _build_profile_traits_lines(archetype_metrics, fallback_metrics=fallback_metrics)
    analysis_lines = _build_profile_character_analysis_lines(archetype_metrics, fallback_metrics=fallback_metrics)
    blocks = [
        "**Caratteristiche dominanti:**",
        *trait_lines,
        "",
        "**Analisi carattere:**",
        *analysis_lines,
    ]
    return "\n".join(blocks)

def _build_advice_lines(metrics: dict[str, Any], *, channel_name: str) -> list[str]:
    cfg = load_json_file(AURA_ARCHETYPES_JSON) or {}
    advice_cfg = cfg.get("default_advice", []) if isinstance(cfg, dict) else []
    if isinstance(advice_cfg, list) and advice_cfg:
        return [str(x) for x in advice_cfg[:3]]
    lines: list[str] = []
    unique = int(metrics.get("unique_interactions", 0) or 0)
    degrade = int(metrics.get("degrade_events", 0) or 0)
    msg_count = int(metrics.get("msg_count", 0) or 0)
    if unique <= 2:
        lines.append("Per migliorare la tua aura potresti coinvolgere più persone in canali diversi.")
    if degrade > 0:
        lines.append("Potresti bilanciare meglio i toni nei momenti di confronto acceso.")
    if msg_count < 5:
        lines.append(f"Ti farebbe bene partecipare di più in {channel_name} con messaggi brevi ma frequenti.")
    if not lines:
        lines.append("Continua così: il tuo contributo è già ben bilanciato.")
    return lines[:3]


@dataclass
class ChannelAuraTopUserItem:
    user_id: str
    score: int
    trend_emoji: str
    trend_comment: str
    rank: int


@dataclass
class ChannelAuraMissionTrend:
    assigned_role1: int
    assigned_role2: int
    completed_role1: int
    completed_role2: int
    eligible_role1: int
    eligible_role2: int
    trend_role1: tuple[str, str]
    trend_role2: tuple[str, str]


@dataclass
class ChannelAuraEmbedData:
    positive_points: int
    negative_points: int
    users_count: int
    top_users: list[ChannelAuraTopUserItem]
    positive_reasons: list[tuple[str, int]]
    negative_reasons: list[tuple[str, int]]
    missions: ChannelAuraMissionTrend
    advice_lines: list[str]


def _rank_emoji(rank: int) -> str:
    if rank == 1:
        return "🥇"
    if rank == 2:
        return "🥈"
    if rank == 3:
        return "🥉"
    keycaps = {4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}
    return keycaps.get(rank, f"{rank}.")


def build_channel_aura_advice(
    *,
    positive_points: int,
    negative_points: int,
    users_count: int,
    mission_completed: int,
    top_positive_reason: str | None = None,
) -> list[str]:
    lines: list[str] = []
    if users_count <= 1:
        lines.append("Coinvolgete più persone: la diversità delle interazioni aumenta l'Aura del canale.")
    if mission_completed <= 0:
        lines.append("Provate a completare più missioni giornaliere: sono tra le fonti più affidabili di P.A.")
    if negative_points < 0 and abs(negative_points) >= max(20, positive_points // 2):
        lines.append("Riducete i comportamenti penalizzati: nel periodo i malus hanno pesato molto.")
    if positive_points <= 0:
        lines.append("Aumentate la partecipazione con messaggi utili e continui per generare Aura positiva.")
    if top_positive_reason:
        lines.append(f"Potete spingere ancora su '{top_positive_reason}' per consolidare il trend positivo.")
    if not lines:
        lines.append("Buon equilibrio Aura: mantenete costanza e coinvolgimento per continuare a crescere.")
    return lines[:3]


def _shorten_with_ellipsis(text: str, *, max_len: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= max_len:
        return clean
    return clean[: max(0, max_len - 1)].rstrip() + "…"


def _compact_trend_comment(comment: str) -> str:
    low = str(comment or "").lower()
    if "nuovo ingresso" in low:
        return "nuovo ingresso nel ranking"
    if "sale" in low and "classifica" in low:
        return "sale in classifica"
    if "perde" in low and "posizion" in low:
        return "perde posizioni"
    if "calo" in low:
        return "in calo rispetto al periodo precedente"
    if "crescita" in low or "miglior" in low:
        return "in crescita rispetto al periodo precedente"
    if "stabile" in low:
        return "stabile nel periodo"
    return _shorten_with_ellipsis(comment, max_len=52) or "stabile nel periodo"


def _build_points_lines(
    *,
    positive_reasons: list[tuple[str, int]],
    negative_reasons: list[tuple[str, int]],
    max_positive: int,
    max_negative: int,
) -> list[str]:
    lines: list[str] = []
    positives = sorted(((reason, int(total)) for reason, total in positive_reasons if int(total) > 0), key=lambda item: item[1], reverse=True)
    negatives = sorted(((reason, int(total)) for reason, total in negative_reasons if int(total) < 0), key=lambda item: abs(item[1]), reverse=True)

    if positives:
        lines.append("😇 Punti assegnati:")
        for idx, (reason, total) in enumerate(positives[:max_positive], start=1):
            lines.append(f"{idx}) +{total} P.A. {reason}")

    if negatives and max_negative > 0:
        if lines:
            lines.append("")
        lines.append("😈 Punti revocati:")
        for idx, (reason, total) in enumerate(negatives[:max_negative], start=1):
            lines.append(f"{idx}) {total} P.A. {reason}")

    if not lines:
        lines.append("• Nessun dato rilevante nel periodo.")
    return lines


def _add_field_with_chunks(embed: discord.Embed, *, name: str, value: str) -> None:
    for part_idx, piece in enumerate(_split_field_chunks(value, 1024)):
        embed.add_field(name=name if part_idx == 0 else f"{name} (cont.)", value=piece, inline=False)


def _compose_channel_aura_embed(
    *,
    title: str,
    data: ChannelAuraEmbedData,
    compact_points: tuple[int, int],
    compact_top_comments: bool,
    advice_limit: int,
    compact_missions: bool,
    compact_advice: bool,
    footer_text: str | None,
) -> discord.Embed:
    embed = discord.Embed(title=title, color=0x5865F2)
    _add_field_with_chunks(
        embed,
        name="📈 PANORAMICA",
        value=(
            f"• Punti assegnati: **+{int(data.positive_points)}**\n"
            f"• Punti rimossi: **{abs(int(data.negative_points))}**\n"
            f"• Utenti coinvolti: **{int(data.users_count)}**"
        ),
    )

    rank_lines = [
        f"• {_rank_emoji(item.rank)}{item.trend_emoji} **+{item.score} P.A.** → <@{item.user_id}> — {(_compact_trend_comment(item.trend_comment) if compact_top_comments else _shorten_with_ellipsis(item.trend_comment, max_len=70))}"
        for item in data.top_users[:10]
    ]
    _add_field_with_chunks(
        embed,
        name="🏆 CLASSIFICA",
        value="\n".join(rank_lines) or "• Nessun dato rilevante nel periodo.",
    )

    points_lines = _build_points_lines(
        positive_reasons=data.positive_reasons,
        negative_reasons=data.negative_reasons,
        max_positive=compact_points[0],
        max_negative=compact_points[1],
    )
    _add_field_with_chunks(
        embed,
        name="🕹️ MOTIVAZIONI",
        value="\n".join(points_lines),
    )

    m = data.missions
    role1_emoji, role1_comment = m.trend_role1
    role2_emoji, role2_comment = m.trend_role2
    role1_ratio = f"{m.completed_role1}/{m.eligible_role1}" if m.eligible_role1 > 0 else "0/0"
    role2_ratio = f"{m.completed_role2}/{m.eligible_role2}" if m.eligible_role2 > 0 else "0/0"
    mission_value = (
        f"🧭 Assegnate:\n"
        f"• {m.assigned_role1} missioni da completare a ruolo1\n"
        f"• {m.assigned_role2} missioni da completare a ruolo2\n\n"
        f"🎯 Risultati:\n"
        f"• {role1_ratio} completate da ruolo1 {role1_emoji} {_compact_trend_comment(role1_comment)}\n"
        f"• {role2_ratio} completate da ruolo2 {role2_emoji} {_compact_trend_comment(role2_comment)}"
        if compact_missions
        else (
            "🧭 Assegnate:\n"
            f"• {m.assigned_role1} missioni da completare a ruolo1\n"
            f"• {m.assigned_role2} missioni da completare a ruolo2\n\n"
            "🎯 Risultati:\n"
            f"• {role1_ratio} completate da ruolo1 {role1_emoji} {_compact_trend_comment(role1_comment)}\n"
            f"• {role2_ratio} completate da ruolo2 {role2_emoji} {_compact_trend_comment(role2_comment)}"
        )
    )
    _add_field_with_chunks(
        embed,
        name="📜 MISSIONI",
        value=mission_value,
    )

    advice_max_len = 80 if compact_advice else 120
    advice_lines = [_shorten_with_ellipsis(line, max_len=advice_max_len) for line in data.advice_lines[:advice_limit]]
    _add_field_with_chunks(
        embed,
        name="✨ I CONSIGLI DEL BARCELLOMETRO",
        value="\n".join(f"• {line}" for line in advice_lines) or "• Nessun consiglio disponibile.",
    )
    attach_footer_meta(embed, service_name="aura", used_local_processing=True)
    return embed


def build_channel_aura_embed(
    *,
    data: ChannelAuraEmbedData,
    title: str = "🗒️ DETTAGLI PUNTI AURA (Pag 2/2)",
    footer_text: str = "Il sistema PUNTI AURA è in fase di sviluppo. I dati potrebbero non essere accurati.",
    max_chars: int = AURA_DETAILS_INTERNAL_BUDGET,
) -> discord.Embed:
    stages = [
        ((6, 2), False, 3, False, False),
        ((4, 1), False, 3, False, False),
        ((3, 1), True, 2, True, True),
        ((2, 0), True, 2, True, True),
    ]

    first_size = 0
    fallback_embed: discord.Embed | None = None
    for idx, (compact_points, compact_top_comments, advice_limit, compact_missions, compact_advice) in enumerate(stages):
        candidate = _compose_channel_aura_embed(
            title=title,
            data=data,
            compact_points=compact_points,
            compact_top_comments=compact_top_comments,
            advice_limit=advice_limit,
            compact_missions=compact_missions,
            compact_advice=compact_advice,
            footer_text=footer_text,
        )
        size = _estimate_embed_size(candidate)
        if idx == 0:
            first_size = size
        fallback_embed = candidate
        if size <= max_chars:
            logger.debug("aura_embed_chars_before_compaction=%s aura_embed_chars_after_compaction=%s", first_size, size)
            return candidate

    assert fallback_embed is not None
    logger.debug("aura_embed_chars_before_compaction=%s aura_embed_chars_after_compaction=%s", first_size, _estimate_embed_size(fallback_embed))
    return fallback_embed


def build_aura_embeds(
    *,
    profile_name: str,
    aura_payload: AuraRenderPayload,
    include_sections: list[str],
    details_title_prefix: str,
    details_embeds_max: int,
    ledger_lines: list[str],
) -> list[discord.Embed]:
    main = discord.Embed(
        title=f"✨ RESOCONTO AURA \"{aura_payload.username}\"",
        color=0x5865F2,
        description=_build_main_aura_description(aura_payload=aura_payload),
    )
    attach_footer_meta(main, service_name="aura", used_local_processing=True)

    details_sections: list[tuple[str, str]] = []
    profile_section: tuple[str, str] | None = None
    metrics = json.loads(aura_payload.metrics_json) if aura_payload.metrics_json else {}
    details_sections.append(("🕹️ MOTIVAZIONI", _compact_bullets(_score_lines(ledger_lines), fallback="Nessun dato rilevante nel periodo.")))

    if "details.missions" in include_sections:
        details_sections.append(("📜 MISSIONI QUOTIDIANE", _compact_bullets(_build_missions(metrics, aura_payload.archetype_metrics, aura_payload.assigned_missions), fallback="Nessuna per oggi.")))
    if "details.profile" in include_sections:
        profile_section = ("👤 PROFILO PERSONALE", _build_profile_section_text(aura_payload.archetype_metrics, fallback_metrics=metrics))
    if "details.advice" in include_sections:
        details_sections.append(("🧭 CONSIGLI PERSONALIZZATI", _compact_bullets(_build_advice_lines(metrics, channel_name=aura_payload.channel_name), fallback="Nessun dato rilevante nel periodo.")))
    if "details.points_timeline" in include_sections and aura_payload.points_timeline_lines is not None:
        details_sections.append(("🧾 BREAKDOWN PUNTI", _compact_bullets(aura_payload.points_timeline_lines, fallback="Nessun dato rilevante nel periodo.")))
    if "details.metrics_aggregated" in include_sections:
        details_sections.append((":bricks: METRICHE AGGREGATE", "Dettagli completi nel file allegato."))

    if "details.note.role1" in include_sections:
        details_sections.append(("📌 NOTE", "• Per conoscere i dettagli sul tuo profilo personale e i consigli su come migliorare la tua aura, abbonati a un piano superiore PRO o PRO MAX. 😉"))
    if "details.note.role2" in include_sections:
        details_sections.append(("📌 NOTE", "• Per avere i consigli su come migliorare la tua aura, abbonati al piano superiore PRO MAX. 😉"))

    if not details_sections and profile_section is None:
        return [main]

    page_size = 3
    page_chunks: list[list[tuple[str, str]]] = []
    for idx in range(0, len(details_sections), page_size):
        page_chunks.append(details_sections[idx : idx + page_size])
    if profile_section is not None:
        if page_chunks:
            page_chunks = [page_chunks[0], [profile_section], *page_chunks[1:]]
        else:
            page_chunks = [[profile_section]]

    max_pages = max(1, details_embeds_max)
    page_chunks = page_chunks[:max_pages]
    total_pages = len(page_chunks)
    details: list[discord.Embed] = []
    tier_label_map = {"role1": "PLUS", "role2": "PRO", "role3": "PRO MAX", "mod": "MOD"}
    tier_label = tier_label_map.get(profile_name, profile_name.upper())

    for page_idx, chunk in enumerate(page_chunks, start=1):
        prefix = details_title_prefix.strip() if details_title_prefix else "🗒️ DETTAGLI AURA"
        embed = discord.Embed(title=f"{prefix} — \"{tier_label}\" (Pag {page_idx}/{total_pages})", color=0x2F3136)
        for name, value in chunk:
            for part_idx, piece in enumerate(_split_field_chunks(value, 1024)):
                embed.add_field(name=name if part_idx == 0 else f"{name} (cont.)", value=piece, inline=False)
        attach_footer_meta(embed, service_name="aura", used_local_processing=True)
        details.append(embed)

    embeds = [main, *details]
    sanitized = _ensure_embed_limits(embeds, max_chars=MAX_EMBED_CHARS)
    return [emb for emb in sanitized if _estimate_embed_size(emb) <= MAX_EMBED_CHARS]
