from __future__ import annotations

from typing import Any


def build_dynamic_archetype_reason(
    archetype_key: str,
    *,
    metrics: dict[str, Any] | None,
    scores: dict[str, Any] | None,
    config: dict[str, Any] | None,
) -> str:
    data = metrics or {}
    score_data = scores or {}
    cfg = config or {}

    def _num(key: str, default: float = 0.0) -> float:
        value = data.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    msg_count = _num("msg_count")
    unique_interactions = _num("unique_interactions")
    channels_active = _num("channels_active", _num("channel_diversity"))
    replies_sent = _num("replies_sent")
    reply_ratio = replies_sent / max(msg_count, 1.0)
    active_days = _num("active_days")
    consistency_rate = _num("consistency_rate", _num("daily_regularity"))
    invigorate = _num("invigorate_events")
    degrade = _num("degrade_events")
    quality_counter = _num("quality_counter")
    first_message_of_day = _num("first_message_of_day")
    mentions_unique_users = _num("mentions_unique_users")
    climate_balance = max(0.0, invigorate - degrade)
    monopoly_rate = max(0.0, min(1.0, _num("monopoly_rate", (msg_count - unique_interactions) / max(msg_count, 1.0))))
    diversity_rate = max(0.0, min(1.0, _num("diversity_rate", unique_interactions / max(msg_count, 1.0))))
    impact_per_message = max(0.0, _num("impact_per_message", (invigorate * 1.5 + quality_counter + replies_sent) / max(msg_count, 1.0)))

    fallback = str(cfg.get("profile_reason_template") or cfg.get("description") or "Profilo emerso dalle tue metriche del periodo").strip()

    variants: list[str] = []
    if archetype_key == "dominante":
        if monopoly_rate >= 0.65:
            variants.append("Hai concentrato molti messaggi in pochi spazi, occupando una quota ampia della conversazione")
        if msg_count >= 30 and impact_per_message >= 1.0:
            variants.append("Sei intervenuto molto e con forte impatto, prendendo spesso il centro della scena")
    elif archetype_key == "collante":
        if unique_interactions >= 6 and channels_active >= 3:
            variants.append("Hai interagito con persone diverse in più canali, aiutando a tenere insieme il ritmo della community")
        if reply_ratio >= 0.35:
            variants.append("Hai collegato momenti e persone diverse con interazioni distribuite e continue")
    elif archetype_key == "costante":
        if active_days >= 10 and consistency_rate >= 0.55:
            variants.append("Hai avuto una presenza costante e regolare nel tempo")
        if 8 <= msg_count <= 45 and active_days >= 8:
            variants.append("Sei rimasto presente con continuità senza concentrare tutto in pochi momenti")
    elif archetype_key == "silenzioso":
        if msg_count <= 12 and active_days >= 2:
            variants.append("Hai avuto una presenza discreta: ci sei stato, ma intervenendo solo quando sentivi che serviva")
        if impact_per_message <= 0.9 and monopoly_rate <= 0.25:
            variants.append("Hai mantenuto un profilo poco invasivo, osservando più di quanto hai spinto la conversazione")
    elif archetype_key == "ascoltatore":
        if reply_ratio >= 0.45 and monopoly_rate <= 0.3:
            variants.append("Hai sostenuto il dialogo senza occupare troppo spazio, con una presenza più attenta che invasiva")
        if quality_counter >= 2:
            variants.append("Hai partecipato in modo misurato, favorendo ascolto e continuità nel confronto")
    elif archetype_key == "esploratore_sociale":
        if channels_active >= 3 and unique_interactions >= 6:
            variants.append("Ti sei mosso tra più canali e persone, evitando di restare chiuso in un solo spazio")
        if mentions_unique_users >= 4:
            variants.append("Hai cercato contatto con utenti diversi, distribuendo la tua presenza in più direzioni")
    elif archetype_key == "lampo":
        if msg_count <= 15 and impact_per_message >= 1.3:
            variants.append("Hai parlato meno, ma quando sei entrato hai lasciato un impatto netto")
        if msg_count <= 14 and invigorate >= 2:
            variants.append("Con pochi interventi sei riuscito comunque a smuovere il ritmo della conversazione")
    elif archetype_key == "scintilla":
        if first_message_of_day >= 3:
            variants.append("Hai acceso spesso il ritmo delle conversazioni prendendo iniziativa nei momenti iniziali")
        if impact_per_message >= 1.2:
            variants.append("I tuoi interventi hanno spesso dato il via ai momenti più vivi")
    elif archetype_key == "pacificatore":
        if climate_balance >= 2 and degrade <= 1:
            variants.append("Hai mantenuto toni più costruttivi e un impatto equilibrato nel clima del server")
        if reply_ratio >= 0.3 and quality_counter >= 2:
            variants.append("Hai favorito uno stile più disteso e collaborativo nelle interazioni")
    elif archetype_key == "agitatore":
        if degrade >= 2 and impact_per_message >= 1.0:
            variants.append("Hai mosso molto il clima del server, alzando l'intensità delle discussioni")
        if impact_per_message >= 1.5:
            variants.append("I tuoi interventi hanno inciso parecchio sul ritmo e sulla temperatura delle conversazioni")
    elif archetype_key == "selettivo":
        if diversity_rate <= 0.3 and reply_ratio >= 0.25:
            variants.append("Hai concentrato le tue energie su pochi contesti e poche persone in modo mirato")
        if channels_active <= 2 and unique_interactions <= 5:
            variants.append("Ti sei mosso in modo più selettivo, preferendo spazi e legami specifici")
    elif archetype_key == "mediatore":
        if reply_ratio >= 0.35 and quality_counter >= 2 and climate_balance >= 1:
            variants.append("Hai aiutato a riequilibrare il confronto con interventi misurati e orientati al dialogo")
        if unique_interactions >= 5 and monopoly_rate <= 0.35:
            variants.append("Hai fatto da ponte tra persone diverse senza spingere troppo il centro della scena")

    if not variants:
        return fallback

    primary = variants[0]
    score_value = score_data.get(archetype_key)
    try:
        if float(score_value) >= 45 and len(variants) > 1:
            primary = f"{variants[0]}, e {variants[1][:1].lower()}{variants[1][1:]}"
    except (TypeError, ValueError):
        pass
    return primary
