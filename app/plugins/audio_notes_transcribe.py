from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import discord
import imageio_ffmpeg

from app.core.service_registry import ServiceRegistry
from app.services.footer import attach_footer_meta

logger = logging.getLogger(__name__)

_AUDIO_EXTENSIONS = {".ogg", ".opus", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".webm"}
_AUDIO_NOTE_TITLE = "🗣️ NOTE AUDIO"
_AUDIO_NOTE_COLOR = discord.Color(0xFFFFFF)
_DISCORD_EMBED_DESCRIPTION_MAX = 4096


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_audio_attachment(attachment: discord.Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("audio/"):
        return True
    _, ext = os.path.splitext(attachment.filename.lower())
    return ext in _AUDIO_EXTENSIONS


def _split_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > max_chars and current:
            parts.append("".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        parts.append("".join(current))
    return parts


def _split_embed_descriptions(text: str, max_chars: int = _DISCORD_EMBED_DESCRIPTION_MAX) -> list[str]:
    safe_max = max(1, min(max_chars, _DISCORD_EMBED_DESCRIPTION_MAX))
    parts = _split_text(text, safe_max)
    split_parts: list[str] = []
    for part in parts:
        if len(part) <= safe_max:
            split_parts.append(part)
            continue
        for idx in range(0, len(part), safe_max):
            split_parts.append(part[idx : idx + safe_max])
    return split_parts or [""]


def _build_audio_note_embed(description: str, *, contributors: list[str] | None = None, used_local_processing: bool = True) -> discord.Embed:
    embed = discord.Embed(title=_AUDIO_NOTE_TITLE, description=description, color=_AUDIO_NOTE_COLOR)
    return attach_footer_meta(embed, service_name="audio_notes", contributors=contributors or [], used_local_processing=used_local_processing)


def _parse_chars_summary_limit(raw_value: str | None) -> int:
    cleaned = (raw_value or "").strip()
    if not cleaned:
        return 0
    try:
        parsed = int(cleaned)
    except ValueError:
        return 0
    return parsed if parsed > 0 else 0


def _should_generate_audio_summary(transcript_text: str, chars_summary_limit: int) -> bool:
    cleaned = transcript_text.strip()
    return chars_summary_limit > 0 and len(cleaned) >= 20 and len(cleaned) > chars_summary_limit


def _build_audio_note_output(*, transcript_text: str, detected_lang: str, translation_text: str | None, summary_text: str | None) -> str:
    output_parts = ["**✍️ Trascrizione:**", transcript_text]
    if detected_lang != "it" and translation_text:
        output_parts.extend(["", "**🇮🇹 Traduzione:**", translation_text])
    if summary_text:
        output_parts.extend(["", "⏲️ **Riassunto:**", summary_text])
    return "\n".join(output_parts).strip()


def _sanitize_transcript_for_summary(text: str) -> str:
    sanitized = text
    replacements: list[tuple[str, str]] = [
        (r"\brompere il cazzo\b", "[espressione volgare]"),
        (r"\brompi il cazzo\b", "[espressione volgare]"),
        (r"\brompe il cazzo\b", "[espressione volgare]"),
        (r"\bvaffanculo\b", "[offesa]"),
        (r"\bstronza\b", "[insulto]"),
        (r"\bstronzo\b", "[insulto]"),
        (r"\btroia\b", "[insulto]"),
        (r"\bputtana\b", "[insulto]"),
        (r"\bcazzo\b", "[volgarità]"),
        (r"\bminchia\b", "[volgarità]"),
        (r"\bmerda\b", "[volgarità]"),
    ]
    for pattern, replacement in replacements:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"[ \t]{2,}", " ", sanitized)
    return sanitized.strip()


def _looks_like_summary_refusal(text: str) -> bool:
    lowered = text.strip().lower()
    suspicious_fragments = {
        "non posso",
        "non sono in grado",
        "non posso aiutarti",
        "non posso fornire",
        "non posso riassumere",
        "contenuto offensivo",
        "linguaggio offensivo",
        "hate speech",
        "violates",
        "policy",
        "mi dispiace",
        "sorry",
        "assist with",
        "qualcos'altro?",
        "posso aiutarti con",
        "non posso elaborare",
    }
    return any(fragment in lowered for fragment in suspicious_fragments)


def _normalize_summary_text(text: str) -> str:
    normalized = text.strip()
    normalized = re.sub(r'^["“”\']+|["“”\']+$', "", normalized).strip()
    normalized = re.sub(r"^(riassunto|summary)\s*:\s*", "", normalized, flags=re.IGNORECASE)
    return normalized.strip()


async def _build_audio_note_summary(ai_service: Any, transcript_text: str) -> tuple[str | None, str | None]:
    if ai_service is None:
        return None, None
    if not ai_service.is_enabled():
        return None, None
    cleaned_transcript = transcript_text.strip()
    if len(cleaned_transcript) < 20:
        return None, None
    sanitized_transcript = _sanitize_transcript_for_summary(cleaned_transcript)
    if not sanitized_transcript:
        return None, None

    system_prompt = (
        "Stai leggendo una trascrizione ASR di una nota audio. "
        "La trascrizione può contenere insulti o volgarità riportati come parte del contenuto. "
        "Il tuo compito è SOLO riassumere in modo neutro e fedele ciò che viene detto. "
        "Non moralizzare, non rifiutare, non inserire avvisi di policy. "
        "Se compaiono espressioni volgari, descrivile in modo neutro senza ripeterle inutilmente. "
        "Massimo 2 frasi brevi, niente elenchi, niente formule introduttive."
    )
    hardened_prompt = (
        "Stai leggendo una trascrizione ASR di una nota audio con possibili volgarità. "
        "Produci direttamente solo il riassunto neutro e fedele in massimo 2 frasi brevi. "
        "Non rispondere con rifiuti o avvisi; produci direttamente solo il riassunto. "
        "Niente elenchi, niente formule introduttive."
    )

    async def _request_summary(prompt: str) -> str:
        return await ai_service.ask_for_task(
            "audio_summary",
            sanitized_transcript,
            prompt,
            timeout_seconds=20,
        )

    try:
        summary_text = _normalize_summary_text(await _request_summary(system_prompt))
    except Exception:
        logger.warning("Audio note summary generation failed", exc_info=True)
        return None, None

    if not summary_text or _looks_like_summary_refusal(summary_text):
        logger.warning("Audio note summary rejected by model output; retrying with hardened prompt")
        try:
            summary_text = _normalize_summary_text(await _request_summary(hardened_prompt))
        except Exception:
            logger.warning("Audio note summary generation failed", exc_info=True)
            return None, None

    if not summary_text or _looks_like_summary_refusal(summary_text):
        logger.warning("Audio note summary generation produced refusal twice; skipping summary")
        return None, None

    return summary_text, ai_service.get_model_display_name("audio_summary")


def _build_audio_footer_contributors(
    *,
    stt_backend_used: str,
    stt_model: str | None,
    translate_backend_used: str,
    translation_model: str | None,
    has_translation_text: bool,
    summary_model: str | None = None,
) -> tuple[list[str], bool]:
    contributors: list[str] = []
    used_local_processing = False

    normalized_stt_backend = (stt_backend_used or "").strip().lower()
    normalized_translate_backend = (translate_backend_used or "").strip().lower()
    stt_name = (stt_model or "").strip()
    if stt_name:
        contributors.append(stt_name)
    if normalized_stt_backend == "local":
        used_local_processing = True

    if has_translation_text:
        translation_name = (translation_model or "").strip()
        if translation_name:
            contributors.append(translation_name)
        if normalized_translate_backend == "local":
            used_local_processing = True

    summary_name = (summary_model or "").strip()
    if summary_name:
        contributors.append(summary_name)

    deduped: list[str] = []
    seen: set[str] = set()
    for contributor in contributors:
        if contributor in seen:
            continue
        seen.add(contributor)
        deduped.append(contributor)
    return deduped, used_local_processing


def _normalize_lang(value: str) -> str:
    lowered = value.strip().lower()
    if not lowered:
        return "unknown"
    if lowered in {"italian", "ita"}:
        return "it"
    return lowered.split("-")[0]


def _ffprobe_duration(path: str) -> Optional[int]:
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path is None:
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        if ffmpeg_path:
            candidate = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe")
            if os.path.exists(candidate):
                ffprobe_path = candidate
    if ffprobe_path is None:
        return None
    result = subprocess.run(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return int(float(result.stdout.strip()))
    except ValueError:
        return None


def _convert_to_wav(input_path: str, output_path: str) -> bool:
    ffmpeg_path = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
    if not ffmpeg_path:
        return False
    result = subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-i",
            input_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            output_path,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def setup(registry: ServiceRegistry) -> None:
    bot: discord.Client = registry.get("bot")
    database = registry.get("database")
    stt_local = registry.get("stt.local")
    stt_ai = registry.get("stt.ai")
    translate_local = registry.get("translate.local")
    translate_ai = registry.get("translate.ai")
    ai_service = registry.get("ai") if registry.has("ai") else None
    config = registry.get("config")

    queue: asyncio.Queue[tuple[discord.Message, discord.Attachment, discord.Message]] = asyncio.Queue()
    worker_started = False

    async def _get_setting(key: str, default: str) -> str:
        stored = await database.get_setting(key)
        return stored if stored is not None else default

    async def _audio_notes_enabled() -> bool:
        stored = await database.get_setting("audio_notes.enabled")
        if stored is None:
            return False
        return stored.lower() in {"1", "true", "yes", "y"}

    async def _handle_message(message: discord.Message) -> None:
        if message.author.bot and config.ignore_bots:
            return
        if not message.guild:
            return
        if not await _audio_notes_enabled():
            return
        if not message.attachments:
            return
        enabled_channel = await database.is_channel_enabled(str(message.channel.id))
        if not enabled_channel:
            return

        for attachment in message.attachments:
            if not _is_audio_attachment(attachment):
                continue
            queue_max = int(await _get_setting("audio_notes.queue_max", os.getenv("AUDIO_NOTES_QUEUE_MAX", "50")))
            if queue.qsize() >= queue_max:
                await message.reply(embed=_build_audio_note_embed("⏳ Troppi audio in coda, riprova tra poco.", used_local_processing=True))
                return
            reply = await message.reply(embed=_build_audio_note_embed("🎙️ Nota audio ricevuta, sto trascrivendo…", used_local_processing=True))
            await queue.put((message, attachment, reply))
            return

    async def _process_job(message: discord.Message, attachment: discord.Attachment, reply: discord.Message) -> None:
        max_mb = int(await _get_setting("audio_notes.max_mb", os.getenv("AUDIO_NOTES_MAX_MB", "25")))
        max_duration = int(await _get_setting("audio_notes.max_duration_s", os.getenv("AUDIO_NOTES_MAX_DURATION_S", "180")))
        max_chars = int(await _get_setting("audio_notes.discord_max_chars", os.getenv("AUDIO_NOTES_DISCORD_MAX_CHARS", "1900")))
        chars_summary_raw = await _get_setting("audio_notes.chars_summary", "")
        embed_max_chars = max(1, min(max_chars, _DISCORD_EMBED_DESCRIPTION_MAX))
        chars_summary_limit = _parse_chars_summary_limit(chars_summary_raw)

        size_mb = attachment.size / (1024 * 1024)
        if size_mb > max_mb:
            await reply.edit(content=None, embed=_build_audio_note_embed("❌ Audio troppo grande per la trascrizione."))
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = os.path.join(tmpdir, attachment.filename)
            wav_path = os.path.join(tmpdir, "audio.wav")
            data = await attachment.read()
            with open(raw_path, "wb") as handle:
                handle.write(data)

            duration = _ffprobe_duration(raw_path)
            if duration is not None and duration > max_duration:
                await reply.edit(content=None, embed=_build_audio_note_embed("❌ Audio troppo lungo per la trascrizione."))
                return
            if not _convert_to_wav(raw_path, wav_path):
                await reply.edit(content=None, embed=_build_audio_note_embed("❌ Errore durante la conversione audio."))
                return

            stt_backend = (await _get_setting("stt.backend", "local")).lower()
            stt_used = "local"
            configured_language_hint = ((await _get_setting("stt.local.language_hint", "auto")) or "auto").strip().lower()
            audio_notes_language_override = "auto"
            try:
                if stt_backend == "ai":
                    transcript = await stt_ai.transcribe(wav_path, language_hint_override=audio_notes_language_override)
                    stt_used = "ai"
                else:
                    transcript = await stt_local.transcribe(wav_path, language_hint_override=audio_notes_language_override)
            except Exception:
                logger.exception("STT failed, falling back to local")
                transcript = await stt_local.transcribe(wav_path, language_hint_override=audio_notes_language_override)
                stt_used = "local"

            original_transcript_text = transcript.text.strip()
            translation_text: Optional[str] = None
            translation_model: Optional[str] = None
            summary_text: Optional[str] = None
            summary_model: Optional[str] = None
            target_lang = await _get_setting("translate.target_lang", "it")
            translate_backend = (await _get_setting("translate.backend", "local")).lower()
            translate_used = translate_backend
            detected_lang = _normalize_lang(transcript.detected_language)
            target_lang_norm = _normalize_lang(target_lang)

            logger.debug(
                "Audio note STT backend=%s model=%s configured_hint=%s override_hint=%s effective_hint=%s detected_language=%s text_preview=%r",
                stt_used,
                transcript.model,
                configured_language_hint,
                audio_notes_language_override,
                transcript.language_hint,
                transcript.detected_language,
                original_transcript_text[:120],
            )

            should_translate = detected_lang != target_lang_norm
            if should_translate:
                try:
                    if translate_backend == "ai":
                        translation = await translate_ai.translate(original_transcript_text, target_lang)
                        translate_used = "ai"
                    else:
                        translation = await translate_local.translate(original_transcript_text, target_lang)
                        translate_used = "local"
                    translation_text = translation.text.strip() if translation.text else None
                    translation_model = translation.model
                except Exception:
                    logger.exception("Translation failed; skipping translation")
                    translation_text = None
                    translation_model = None

            should_summarize = _should_generate_audio_summary(original_transcript_text, chars_summary_limit)
            if should_summarize:
                summary_text, summary_model = await _build_audio_note_summary(ai_service, original_transcript_text)

            logger.debug(
                "Audio note translation decision detected=%s target=%s should_translate=%s translated=%s",
                detected_lang,
                target_lang_norm,
                should_translate,
                bool(translation_text),
            )

            full_output = _build_audio_note_output(
                transcript_text=original_transcript_text,
                detected_lang=detected_lang,
                translation_text=translation_text,
                summary_text=summary_text,
            )

            contributors, used_local_processing = _build_audio_footer_contributors(
                stt_backend_used=stt_used,
                stt_model=transcript.model,
                translate_backend_used=translate_used,
                translation_model=translation_model,
                has_translation_text=bool(detected_lang != "it" and translation_text),
                summary_model=summary_model if summary_text else None,
            )

            chunks = _split_embed_descriptions(full_output, embed_max_chars)
            await reply.edit(content=None, embed=_build_audio_note_embed(chunks[0], contributors=contributors, used_local_processing=used_local_processing))
            for idx, chunk in enumerate(chunks[1:], start=2):
                part_description = f"**Parte {idx}/{len(chunks)}**\n\n{chunk}"
                await message.reply(embed=_build_audio_note_embed(part_description, contributors=contributors, used_local_processing=used_local_processing))

            meta: dict[str, Any] = {
                "discord_message_id": str(message.id),
                "bot_reply_message_id": str(reply.id),
                "attachment_filename": attachment.filename,
                "size_mb": round(size_mb, 2),
                "duration_s": duration,
                "lang": transcript.detected_language,
                "language_hint": transcript.language_hint,
                "stt_backend": stt_used,
                "stt_model": transcript.model,
                "translate_backend": translate_used,
                "translate_model": translation_model,
            }

            await database.insert_message(
                message_id=str(uuid4()),
                guild_id=str(message.guild.id),
                channel_id=str(message.channel.id),
                author_id=str(message.author.id),
                ts=_now_iso(),
                content=original_transcript_text,
                reply_to_message_id=str(message.id),
                mentions=[],
                attachments=[],
                embeds=[{"audio_note_meta": meta, "source": "audio_note_stt"}],
            )
            if detected_lang != "it" and translation_text:
                await database.insert_message(
                    message_id=str(uuid4()),
                    guild_id=str(message.guild.id),
                    channel_id=str(message.channel.id),
                    author_id=str(message.author.id),
                    ts=_now_iso(),
                    content=translation_text,
                    reply_to_message_id=str(message.id),
                    mentions=[],
                    attachments=[],
                    embeds=[{"audio_note_meta": meta, "source": "audio_note_it"}],
                )

    async def _worker() -> None:
        while True:
            message, attachment, reply = await queue.get()
            try:
                await _process_job(message, attachment, reply)
            except Exception:  # noqa: BLE001
                logger.exception("Audio note processing failed")
                await reply.edit(
                    content=None,
                    embed=_build_audio_note_embed("❌ Errore durante la trascrizione della nota audio."),
                )
            finally:
                queue.task_done()

    async def handle_ready() -> None:
        nonlocal worker_started
        if worker_started:
            return
        worker_started = True
        asyncio.create_task(_worker())

    bot.add_listener(handle_ready, "on_ready")
    bot.add_listener(_handle_message, "on_message")
