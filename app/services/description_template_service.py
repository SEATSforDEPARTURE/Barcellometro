from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

import discord

from app.services.embed_public_service_keys import (
    list_embed_service_aliases,
    list_public_embed_service_keys,
    resolve_public_embed_service_key,
)
from app.services.embed_status_placeholders import placeholder_names_for_system
from app.services.database import DatabaseService
from app.shared.discord.embed_body import DISCORD_DESCRIPTION_MAX, format_standard_description

_DESCRIPTION_TEMPLATE_KEY_PREFIX = "description_template:"
_DESCRIPTION_ENABLED_KEY = "description_template.enabled"
_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_MENTION_RE = re.compile(r"<@!?&?#?\d+>")

_SERVICE_PLACEHOLDERS: dict[str, tuple[str, ...]] = {
    "audio": ("audio_intro", "is_first_today", "count_today"),
}


class InvalidDescriptionTemplateError(ValueError):
    pass


@dataclass(slots=True)
class DescriptionTemplateStatusSnapshot:
    enabled: bool
    total_services: int
    custom_templates: dict[str, str]


class DescriptionTemplateService:
    def __init__(self, database: DatabaseService) -> None:
        self._database = database

    def _key_for_service(self, service: str) -> str:
        return f"{_DESCRIPTION_TEMPLATE_KEY_PREFIX}{self.normalize_service_name(service)}"

    def normalize_service_name(self, service: str) -> str:
        resolved = resolve_public_embed_service_key(service, system="description")
        if resolved is None:
            raise InvalidDescriptionTemplateError("Provide a valid service name")
        return resolved

    def allowed_placeholders(self, service: str) -> set[str]:
        service_name = self.normalize_service_name(service)
        generic = placeholder_names_for_system("description") - {"audio_intro", "is_first_today", "count_today"}
        return generic.union(_SERVICE_PLACEHOLDERS.get(service_name, ()))

    def validate_template(self, service: str, template: str) -> str:
        cleaned = (template or "").strip()
        if not cleaned:
            raise InvalidDescriptionTemplateError("Template cannot be empty")
        if len(cleaned) > DISCORD_DESCRIPTION_MAX:
            raise InvalidDescriptionTemplateError(f"Template too long (max {DISCORD_DESCRIPTION_MAX} chars)")

        allowed = self.allowed_placeholders(service)
        detected = set(_PLACEHOLDER_RE.findall(cleaned))
        invalid = sorted(placeholder for placeholder in detected if placeholder not in allowed)
        if invalid:
            suggestions: list[str] = []
            for placeholder in invalid:
                candidates = difflib.get_close_matches(placeholder, sorted(allowed), n=1, cutoff=0.6)
                if candidates:
                    suggestions.append(f"{placeholder} → {candidates[0]}")
            suggestion_text = f" Suggestions: {', '.join(suggestions)}." if suggestions else ""
            raise InvalidDescriptionTemplateError(
                f"Invalid placeholders: {', '.join(invalid)}.{suggestion_text}"
            )

        return cleaned

    async def set_template(self, service: str, template: str) -> str:
        service_name = self.normalize_service_name(service)
        validated = self.validate_template(service_name, template)
        await self._database.set_setting(self._key_for_service(service_name), validated)
        return validated

    async def set_enabled(self, enabled: bool) -> None:
        await self._database.set_setting(_DESCRIPTION_ENABLED_KEY, "true" if enabled else "false")

    async def is_enabled(self) -> bool:
        stored = await self._database.get_setting(_DESCRIPTION_ENABLED_KEY)
        if stored is None:
            await self._database.set_setting(_DESCRIPTION_ENABLED_KEY, "true")
            return True
        return stored.lower() in {"1", "true", "yes", "y"}

    async def get_template(self, service: str) -> str | None:
        service_name = self.normalize_service_name(service)
        for alias in list_embed_service_aliases(service_name):
            value = await self._database.get_setting(f"{_DESCRIPTION_TEMPLATE_KEY_PREFIX}{alias}")
            cleaned = (value or "").strip()
            if cleaned:
                return cleaned
        return None

    async def reset_template(self, service: str) -> None:
        service_name = self.normalize_service_name(service)
        for alias in list_embed_service_aliases(service_name):
            await self._database.delete_setting(f"{_DESCRIPTION_TEMPLATE_KEY_PREFIX}{alias}")

    def _sanitize_value(self, value: Any) -> str:
        text = "" if value is None else str(value)
        text = _MENTION_RE.sub("utente", text)
        text = discord.utils.escape_markdown(text, as_needed=False)
        return text.strip()

    def _build_template_context(self, *, service: str, context: dict[str, Any] | None = None) -> dict[str, str]:
        now = datetime.utcnow()
        base_context = {
            "service_name": service,
            "audio_intro": "Leggiamo cosa ci dice",
            "ordinal_today": "primo",
            "is_first_today": "True",
            "count_today": "1",
        }
        if context:
            base_context.update(context)

        user_name = self._sanitize_value(base_context.get("user_name") or "utente")
        ordinal_today = self._sanitize_value(base_context.get("ordinal_today") or "primo")

        rendered_context: dict[str, str] = {
            "user_name": user_name,
            "user_bold": f"**{user_name}**",
            "service_name": self._sanitize_value(base_context.get("service_name") or service),
            "ordinal_today": ordinal_today,
            "ordinal_today_bold": f"**{ordinal_today}**",
            "audio_intro": self._sanitize_value(base_context.get("audio_intro") or "Leggiamo cosa ci dice"),
            "is_first_today": self._sanitize_value(base_context.get("is_first_today") or "False"),
            "count_today": self._sanitize_value(base_context.get("count_today") or "0"),
            "weekday": str(now.weekday()),
        }

        for key, value in (context or {}).items():
            rendered_context[key] = self._sanitize_value(value)

        return rendered_context

    def _render_template(self, template: str, values: dict[str, str]) -> str:
        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            value = values.get(key)
            return value if value else "—"

        rendered = _PLACEHOLDER_RE.sub(_replace, template)
        rendered = _MENTION_RE.sub("utente", rendered)
        rendered = rendered.replace("<@", "<@\u200b")
        return rendered.strip()

    async def render(
        self,
        *,
        service: str,
        context: dict[str, Any] | None,
        fallback: str | Callable[[], str],
        respect_global_toggle: bool = True,
    ) -> str:
        service_name = self.normalize_service_name(service)
        if respect_global_toggle and not await self.is_enabled():
            fallback_text = fallback() if callable(fallback) else fallback
            return format_standard_description(self._sanitize_value(fallback_text), italic=True)
        template = await self.get_template(service_name)
        if template is None:
            fallback_text = fallback() if callable(fallback) else fallback
            return format_standard_description(self._sanitize_value(fallback_text), italic=True)

        rendered = self._render_template(template, self._build_template_context(service=service_name, context=context))
        return format_standard_description(rendered, italic=True)

    async def render_preview(
        self,
        *,
        service: str,
        context: dict[str, Any] | None = None,
        fallback: str | Callable[[], str] = "Usa default del servizio",
    ) -> str:
        return await self.render(service=service, context=context, fallback=fallback, respect_global_toggle=False)

    async def build_status_snapshot(self) -> DescriptionTemplateStatusSnapshot:
        custom_templates: dict[str, str] = {}
        for service_name in list_public_embed_service_keys(system="description"):
            template = await self.get_template(service_name)
            if template:
                custom_templates[service_name] = template
        return DescriptionTemplateStatusSnapshot(
            enabled=await self.is_enabled(),
            total_services=len(list_public_embed_service_keys(system="description")),
            custom_templates=custom_templates,
        )
