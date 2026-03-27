import asyncio

import discord

from app.services.author import AuthorService, attach_author_meta
from app.services.footer import FooterService, attach_footer_meta
from app.shared.discord.embed_rendering import finalize_embeds_rendering


class _FakeDatabase:
    def __init__(self) -> None:
        self.settings: dict[str, str] = {}

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = value

    async def delete_setting(self, key: str) -> None:
        self.settings.pop(key, None)

    async def execute(self, _query: str, _params: tuple[str, ...]) -> None:
        return None

    async def fetchall(self, query: str, params: tuple[str, ...]):
        prefix = str(params[0]).replace('%', '') if params else ''
        if 'FROM settings' not in query:
            return []
        return [
            {'key': key, 'value': value}
            for key, value in sorted(self.settings.items())
            if not prefix or key.startswith(prefix)
        ]


def test_finalize_embeds_rendering_supports_from_dict_payload_embeds() -> None:
    async def _run() -> None:
        source = discord.Embed(title="Persisted")
        attach_author_meta(source, service_name="riassunto")
        attach_footer_meta(source, service_name="riassunto", contributors=["gpt-4o-mini"], used_local_processing=False)

        payload = source.to_dict()
        reloaded = discord.Embed.from_dict(payload)
        attach_author_meta(reloaded, service_name="riassunto")
        attach_footer_meta(reloaded, service_name="riassunto", contributors=["gpt-4o-mini"], used_local_processing=False)

        author = AuthorService(_FakeDatabase())
        footer = FooterService(_FakeDatabase())

        rendered = await finalize_embeds_rendering(
            [reloaded],
            footer_service=footer,
            author_service=author,
            default_service_name="riassunto",
        )

        assert rendered[0].author.name == "servizio DM CHANNEL SUMMARY"
        assert "Dati elaborati con gpt-4o-mini" in (rendered[0].footer.text or "")

    asyncio.run(_run())


def test_finalize_embeds_rendering_from_dict_respects_minimal_author_and_footer_contract() -> None:
    async def _run() -> None:
        source = discord.Embed(title="Persisted minimal")
        attach_author_meta(
            source,
            service_name="attivita",
            canonical_top_level_command="dmserversummary",
            minimal=True,
        )
        attach_footer_meta(source, service_name="attivita", contributors=["gpt-4o-mini"], used_local_processing=False)

        reloaded = discord.Embed.from_dict(source.to_dict())
        attach_author_meta(
            reloaded,
            service_name="attivita",
            canonical_top_level_command="dmserversummary",
            minimal=True,
        )
        attach_footer_meta(reloaded, service_name="attivita", contributors=["gpt-4o-mini"], used_local_processing=False)

        author = AuthorService(_FakeDatabase())
        footer = FooterService(_FakeDatabase())

        rendered = await finalize_embeds_rendering(
            [reloaded],
            footer_service=footer,
            author_service=author,
            default_service_name="attivita",
        )

        assert rendered[0].author.name == "servizio DM SERVER SUMMARY"
        assert "Dati elaborati con gpt-4o-mini" in (rendered[0].footer.text or "")

    asyncio.run(_run())
