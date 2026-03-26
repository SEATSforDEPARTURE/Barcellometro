from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

import discord

from app.services.database import DatabaseService

IMAGES_ENABLED_KEY = "embed_images.enabled"
IMAGES_GLOBAL_IMAGE_KEY = "embed_images.global_image"
IMAGES_GLOBAL_THUMBNAIL_KEY = "embed_images.global_thumbnail"
IMAGES_SERVICE_IMAGE_PREFIX = "embed_images.service_image."
IMAGES_SERVICE_THUMBNAIL_PREFIX = "embed_images.service_thumbnail."

_IMAGE_META: dict[int, tuple[discord.Embed, "EmbedImagesMeta"]] = {}
_CUSTOM_EMOJI_RE = re.compile(r"<(?P<animated>a?):(?P<name>[A-Za-z0-9_]+):(?P<emoji_id>\d+)>")


@dataclass(slots=True)
class EmbedImagesMeta:
    service_name: str
    image_url: str | None = None
    thumbnail_url: str | None = None
    skip: bool = False
    preserve_existing: bool = False


@dataclass(slots=True)
class EmbedImagesStatusSnapshot:
    enabled: bool
    global_image: str | None
    global_thumbnail: str | None
    service_images: dict[str, str]
    service_thumbnails: dict[str, str]


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _custom_emoji_icon_url(match: re.Match[str]) -> str:
    extension = "gif" if match.group("animated") else "png"
    emoji_id = match.group("emoji_id")
    return f"https://cdn.discordapp.com/emojis/{emoji_id}.{extension}"


class InvalidEmbedImageUrlError(ValueError):
    pass


def normalize_embed_image_url(value: str | None) -> str:
    cleaned = _clean(value)
    if not cleaned:
        raise InvalidEmbedImageUrlError("Image must be a Discord custom emoji or an http/https image URL")

    emoji_match = _CUSTOM_EMOJI_RE.fullmatch(cleaned)
    if emoji_match is not None:
        return _custom_emoji_icon_url(emoji_match)

    parsed = urlparse(cleaned)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return cleaned

    raise InvalidEmbedImageUrlError("Image must be a Discord custom emoji or an http/https image URL")


def _normalize_optional_url(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    return normalize_embed_image_url(cleaned)


def _is_persistable_service_name(name: str | None) -> bool:
    service = _clean(name)
    return bool(service and service not in {"unknown", "default", "fallback"})


def attach_embed_images_meta(
    embed: discord.Embed,
    *,
    service_name: str,
    image_url: str | None = None,
    thumbnail_url: str | None = None,
    skip: bool = False,
    preserve_existing: bool = False,
) -> discord.Embed:
    _IMAGE_META[id(embed)] = (
        embed,
        EmbedImagesMeta(
            service_name=_clean(service_name) or "unknown",
            image_url=_clean(image_url) or None,
            thumbnail_url=_clean(thumbnail_url) or None,
            skip=bool(skip),
            preserve_existing=bool(preserve_existing),
        ),
    )
    return embed


def attach_embed_images_meta_to_all(
    embeds: Iterable[discord.Embed] | None,
    *,
    service_name: str,
    image_url: str | None = None,
    thumbnail_url: str | None = None,
    skip: bool = False,
    preserve_existing: bool = False,
) -> list[discord.Embed]:
    embed_list = list(embeds or [])
    for embed in embed_list:
        attach_embed_images_meta(
            embed,
            service_name=service_name,
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            skip=skip,
            preserve_existing=preserve_existing,
        )
    return embed_list


def get_embed_images_meta(embed: discord.Embed) -> EmbedImagesMeta | None:
    item = _IMAGE_META.get(id(embed))
    if item is None:
        return None
    tracked_embed, meta = item
    if tracked_embed is not embed:
        _IMAGE_META.pop(id(embed), None)
        return None
    return meta


def pop_embed_images_meta(embed: discord.Embed) -> EmbedImagesMeta | None:
    item = _IMAGE_META.pop(id(embed), None)
    if item is None:
        return None
    tracked_embed, meta = item
    if tracked_embed is not embed:
        return None
    return meta


class EmbedImagesService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    async def set_enabled(self, enabled: bool) -> None:
        await self._database.set_setting(IMAGES_ENABLED_KEY, "true" if enabled else "false")

    async def is_enabled(self) -> bool:
        stored = await self._database.get_setting(IMAGES_ENABLED_KEY)
        if stored is None:
            await self._database.set_setting(IMAGES_ENABLED_KEY, "true")
            return True
        return stored.lower() in {"1", "true", "yes", "y"}

    async def set_global_image(self, image: str | None) -> None:
        await self._set_or_clear(IMAGES_GLOBAL_IMAGE_KEY, _normalize_optional_url(image))

    async def set_global_thumbnail(self, thumbnail: str | None) -> None:
        await self._set_or_clear(IMAGES_GLOBAL_THUMBNAIL_KEY, _normalize_optional_url(thumbnail))

    async def set_service_image(self, service_name: str, image: str | None) -> None:
        service = _clean(service_name)
        if not service:
            return
        await self._set_or_clear(f"{IMAGES_SERVICE_IMAGE_PREFIX}{service}", _normalize_optional_url(image))

    async def set_service_thumbnail(self, service_name: str, thumbnail: str | None) -> None:
        service = _clean(service_name)
        if not service:
            return
        await self._set_or_clear(f"{IMAGES_SERVICE_THUMBNAIL_PREFIX}{service}", _normalize_optional_url(thumbnail))

    async def get_global_image(self) -> str | None:
        return _clean(await self._database.get_setting(IMAGES_GLOBAL_IMAGE_KEY)) or None

    async def get_global_thumbnail(self) -> str | None:
        return _clean(await self._database.get_setting(IMAGES_GLOBAL_THUMBNAIL_KEY)) or None

    async def get_service_images(self) -> dict[str, str]:
        return await self._get_prefixed_settings(IMAGES_SERVICE_IMAGE_PREFIX)

    async def get_service_thumbnails(self) -> dict[str, str]:
        return await self._get_prefixed_settings(IMAGES_SERVICE_THUMBNAIL_PREFIX)

    async def _get_prefixed_settings(self, prefix: str) -> dict[str, str]:
        rows = await self._database.fetchall(
            "SELECT key, value FROM settings WHERE key LIKE ? ORDER BY key",
            (f"{prefix}%",),
        )
        out: dict[str, str] = {}
        for row in rows:
            key = row["key"]
            value = _clean(row["value"])
            if value:
                out[key.replace(prefix, "", 1)] = value
        return out

    async def resolve_urls(
        self,
        *,
        service_name: str,
        explicit_image_url: str | None = None,
        explicit_thumbnail_url: str | None = None,
    ) -> tuple[str | None, str | None]:
        if _clean(explicit_image_url):
            image_url = _clean(explicit_image_url) or None
        else:
            service_images = await self.get_service_images()
            image_url = service_images.get(service_name) or await self.get_global_image()

        if _clean(explicit_thumbnail_url):
            thumbnail_url = _clean(explicit_thumbnail_url) or None
        else:
            service_thumbnails = await self.get_service_thumbnails()
            thumbnail_url = service_thumbnails.get(service_name) or await self.get_global_thumbnail()

        return image_url, thumbnail_url

    async def apply(self, embed: discord.Embed, *, default_service_name: str = "unknown") -> discord.Embed:
        enabled = await self.is_enabled()
        if not enabled:
            embed.set_image(url=None)
            embed.set_thumbnail(url=None)
            pop_embed_images_meta(embed)
            return embed

        meta = pop_embed_images_meta(embed)
        if meta is None:
            service_name = _clean(default_service_name) or "unknown"
            meta = EmbedImagesMeta(service_name=service_name, preserve_existing=True)

        if meta.skip:
            return embed

        image_before = _clean(getattr(embed.image, "url", None)) or None
        thumb_before = _clean(getattr(embed.thumbnail, "url", None)) or None

        explicit_image = meta.image_url
        explicit_thumbnail = meta.thumbnail_url
        if meta.preserve_existing:
            explicit_image = explicit_image or image_before
            explicit_thumbnail = explicit_thumbnail or thumb_before

        image_url, thumbnail_url = await self.resolve_urls(
            service_name=meta.service_name if _is_persistable_service_name(meta.service_name) else (_clean(default_service_name) or "unknown"),
            explicit_image_url=explicit_image,
            explicit_thumbnail_url=explicit_thumbnail,
        )
        embed.set_image(url=image_url)
        embed.set_thumbnail(url=thumbnail_url)
        return embed

    async def build_status_snapshot(self) -> EmbedImagesStatusSnapshot:
        return EmbedImagesStatusSnapshot(
            enabled=await self.is_enabled(),
            global_image=await self.get_global_image(),
            global_thumbnail=await self.get_global_thumbnail(),
            service_images=await self.get_service_images(),
            service_thumbnails=await self.get_service_thumbnails(),
        )

    async def _set_or_clear(self, key: str, value: str | None) -> None:
        cleaned = _clean(value)
        if not cleaned:
            delete_setting = getattr(self._database, "delete_setting", None)
            if callable(delete_setting):
                await delete_setting(key)
            else:
                await self._database.execute("DELETE FROM settings WHERE key = ?", (key,))
            return
        await self._database.set_setting(key, cleaned)
