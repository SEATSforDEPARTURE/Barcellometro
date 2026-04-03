from __future__ import annotations

from pathlib import Path

import discord

from app.services.author import get_author_meta
from app.services.footer import get_footer_meta
from app.shared.discord.report_embeds import apply_standard_report_style, build_report_cover_embed
from app.shared.discord.report_embeds import send_report_dm_chunks


def test_build_report_cover_embed_attaches_footer_and_author_meta_with_canonical_top_level() -> None:
    embed = build_report_cover_embed(
        title="Cover",
        description="Body",
        service_name="riassunto",
        canonical_top_level_command="dmchannelsummary",
        lines=[("A", "B")],
    )

    footer = get_footer_meta(embed)
    author = get_author_meta(embed)
    assert footer is not None
    assert footer.service_name == "riassunto"
    assert author is not None
    assert author.service_name == "riassunto"
    assert author.canonical_top_level_command == "dmchannelsummary"


def test_apply_standard_report_style_attaches_author_meta_to_all_pages() -> None:
    embeds = [discord.Embed(title="p1"), discord.Embed(title="p2")]

    styled = apply_standard_report_style(
        embeds,
        service_name="resoconto",
        canonical_top_level_command="channelsummary",
        cover_title="T",
    )

    assert styled[0].title == "T"
    for embed in styled:
        footer = get_footer_meta(embed)
        author = get_author_meta(embed)
        assert footer is not None
        assert footer.service_name == "resoconto"
        assert author is not None
        assert author.canonical_top_level_command == "channelsummary"


def test_canonical_top_level_wiring_is_explicit_in_target_command_modules() -> None:
    expected_snippets = {
        "app/plugins/commands_modular/attivita.py": 'canonical_top_level_command="dmserversummary"',
        "app/plugins/commands_modular/aura.py": 'canonical_top_level_command="dmserversummary"',
        "app/plugins/commands_modular/barcello.py": 'canonical_top_level_command="dmchannelsummary"',
        "app/plugins/commands_modular/resoconto.py": 'canonical_top_level_command="channelsummary"',
        "app/plugins/commands_modular/resoconto.py#server": 'canonical_top_level_command="serversummary"',
        "app/plugins/commands_modular/riassunto.py": 'canonical_top_level_command="dmchannelsummary"',
    }

    for key, snippet in expected_snippets.items():
        path = key.split("#", 1)[0]
        source = Path(path).read_text(encoding="utf-8")
        assert snippet in source, f"missing {snippet} in {path}"


def test_send_report_dm_chunks_uses_global_author_pagination_before_split() -> None:
    import asyncio

    from app.shared.discord.author_pipeline import finalize_embeds_author

    class _Destination:
        def __init__(self) -> None:
            self.sent: list[list[discord.Embed]] = []

        async def send(self, *, embeds=None, files=None) -> None:  # noqa: ANN001
            batch = list(embeds or [])
            # Simula auto-finalize lato send per singolo batch.
            await finalize_embeds_author(batch, None, default_service_name="riassunto")
            self.sent.append(batch)

    async def _run() -> None:
        embeds = [discord.Embed(title=f"P{idx}") for idx in range(1, 13)]
        apply_standard_report_style(
            embeds,
            service_name="riassunto",
            canonical_top_level_command="dmchannelsummary",
        )
        destination = _Destination()

        await send_report_dm_chunks(destination, embeds=embeds, chunk_size=10)

        assert len(destination.sent) == 2
        first_batch, second_batch = destination.sent
        assert first_batch[0].author.name == "servizio DM CHANNEL SUMMARY · (Pag. 1/12)"
        assert first_batch[-1].author.name == "servizio DM CHANNEL SUMMARY · (Pag. 10/12)"
        assert second_batch[0].author.name == "servizio DM CHANNEL SUMMARY · (Pag. 11/12)"
        assert second_batch[-1].author.name == "servizio DM CHANNEL SUMMARY · (Pag. 12/12)"

    asyncio.run(_run())
