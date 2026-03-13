from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import discord
import imageio_ffmpeg

from app.core.service_registry import ServiceRegistry

logger = logging.getLogger(__name__)

_AUDIO_EXTENSIONS = {".ogg", ".opus", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".webm"}
_AUDIO_NOTE_TITLE = "🗣️ NOTE AUDIO"
_AUDIO_NOTE_COLOR = discord.Color(0xFFFFFF)
_AUDIO_NOTE_FOOTER = "Barcellometro 1.0"
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


def _build_audio_note_embed(description: str, footer_text: str = _AUDIO_NOTE_FOOTER) -> discord.Embed:
    embed = discord.Embed(title=_AUDIO_NOTE_TITLE, description=description, color=_AUDIO_NOTE_COLOR)
    embed.set_footer(text=footer_text)
    return embed


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
                await message.reply(embed=_build_audio_note_embed("⏳ Troppi audio in coda, riprova tra poco."))
                return
            reply = await message.reply(embed=_build_audio_note_embed("🎙️ Nota audio ricevuta, sto trascrivendo…"))
            await queue.put((message, attachment, reply))
            return

    async def _process_job(message: discord.Message, attachment: discord.Attachment, reply: discord.Message) -> None:
        max_mb = int(await _get_setting("audio_notes.max_mb", os.getenv("AUDIO_NOTES_MAX_MB", "25")))
        max_duration = int(await _get_setting("audio_notes.max_duration_s", os.getenv("AUDIO_NOTES_MAX_DURATION_S", "180")))
        max_chars = int(await _get_setting("audio_notes.discord_max_chars", os.getenv("AUDIO_NOTES_DISCORD_MAX_CHARS", "1900")))
        embed_max_chars = max(1, min(max_chars, _DISCORD_EMBED_DESCRIPTION_MAX))

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
            try:
                if stt_backend == "ai":
                    transcript = await stt_ai.transcribe(wav_path)
                    stt_used = "ai"
                else:
                    transcript = await stt_local.transcribe(wav_path)
            except Exception:
                logger.exception("STT failed, falling back to local")
                transcript = await stt_local.transcribe(wav_path)
                stt_used = "local"

            translation_text: Optional[str] = None
            translation_model: Optional[str] = None
            target_lang = await _get_setting("translate.target_lang", "it")
            translate_backend = (await _get_setting("translate.backend", "local")).lower()
            translate_used = translate_backend
            detected_lang = _normalize_lang(transcript.language)
            target_lang_norm = _normalize_lang(target_lang)
            if detected_lang != target_lang_norm:
                try:
                    if translate_backend == "ai":
                        translation = await translate_ai.translate(transcript.text, target_lang)
                        translate_used = "ai"
                    else:
                        translation = await translate_local.translate(transcript.text, target_lang)
                        translate_used = "local"
                    translation_text = translation.text
                    translation_model = translation.model
                except Exception:
                    logger.exception("Translation failed; skipping translation")
                    translation_text = None
                    translation_model = None

            output_parts = []
            output_parts.append("**✍️ Trascrizione:**")
            output_parts.append(transcript.text)
            if translation_text:
                output_parts.append("")
                output_parts.append("**🇮🇹 Traduzione:**")
                output_parts.append(translation_text)
            full_output = "\n".join(output_parts).strip()

            footer_text = f"Dati elaborati con {transcript.model} · {_AUDIO_NOTE_FOOTER}"
            if translation_text and translation_model:
                footer_text = f"Dati elaborati con {transcript.model} e {translation_model} · {_AUDIO_NOTE_FOOTER}"

            chunks = _split_embed_descriptions(full_output, embed_max_chars)
            await reply.edit(content=None, embed=_build_audio_note_embed(chunks[0], footer_text=footer_text))
            for idx, chunk in enumerate(chunks[1:], start=2):
                part_description = f"**Parte {idx}/{len(chunks)}**\n\n{chunk}"
                await message.reply(embed=_build_audio_note_embed(part_description, footer_text=footer_text))

            meta: dict[str, Any] = {
                "discord_message_id": str(message.id),
                "bot_reply_message_id": str(reply.id),
                "attachment_filename": attachment.filename,
                "size_mb": round(size_mb, 2),
                "duration_s": duration,
                "lang": transcript.language,
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
                content=transcript.text,
                reply_to_message_id=str(message.id),
                mentions=[],
                attachments=[],
                embeds=[{"audio_note_meta": meta, "source": "audio_note_stt"}],
            )
            if translation_text:
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
