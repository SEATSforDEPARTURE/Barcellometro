import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from app.services import campaign_content_fetchers as fetchers
from app.services.author import get_author_meta
from app.services.campaign_content_fetchers import fetch_horoscope_content_async
from app.services.campaign_content_formatter import SIGN_ORDER, build_horoscope_embeds
from app.services.campaign_content_service import CampaignContentService
from app.services.footer import get_footer_meta
from app.shared.discord.author_pipeline import finalize_embeds_author
from app.shared.discord.embed_limits import normalize_embeds_for_discord


def _build_horoscope_payload() -> dict[str, object]:
    signs = {
        sign: {
            "sign": sign,
            "love": "Love " * 20,
            "work": "Work " * 20,
            "money": "Money " * 20,
            "energy": "Energy " * 20,
            "friction": "Friction " * 20,
            "advice": "Advice " * 20,
            "text": "Testo lungo " * 120,
        }
        for sign in SIGN_ORDER
    }
    return {"generated_at": "2026-04-09T08:30:00+00:00", "signs": signs}


def test_fetch_horoscope_content_async_is_resilient_to_single_sign_failures(monkeypatch) -> None:
    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(fetchers.httpx, "AsyncClient", lambda *args, **kwargs: _FakeAsyncClient(), raising=False)
    monkeypatch.setattr(
        "app.services.campaign_content_fetchers._resolve_horoscope_sources",
        lambda _sources: ["https://example.com/api/horoscope"],
    )
    monkeypatch.setattr(
        "app.services.campaign_content_fetchers._http_get",
        lambda _url: (_ for _ in ()).throw(AssertionError("sync _http_get must not be used in async horoscope fetch")),
    )

    async def _fake_fetch(client, *, base_url: str, sign: str, slug: str, timeout: float):
        _ = (client, base_url, slug, timeout)
        if sign == "Toro":
            raise TimeoutError("slow sign endpoint")
        return sign, {"horoscope": f"{sign} fortuna e focus. Opportunità in arrivo."}

    monkeypatch.setattr("app.services.campaign_content_fetchers._fetch_horoscope_sign_async", _fake_fetch)

    async def _run() -> None:
        payload = await fetch_horoscope_content_async(["ohmanda"], request_timeout=0.2, max_concurrency=3)
        assert len(payload["signs"]) == 12
        assert payload["signs"]["Toro"]["fallback_used"] is True
        assert payload["signs"]["Ariete"]["fallback_used"] is False
        assert payload["fallback_used"] is True
        assert payload["used_sources"] == ["example.com"]

    asyncio.run(_run())


def test_horoscope_embed_metadata_survives_normalize_and_finalize_pipeline() -> None:
    embeds = build_horoscope_embeds({}, _build_horoscope_payload())
    assert len(embeds) >= 2
    first = embeds[0]
    assert first.fields
    first.set_field_at(0, name=first.fields[0].name, value="X" * 1300, inline=False)

    normalized = normalize_embeds_for_discord(embeds)
    assert len(normalized) >= 2
    assert all((meta := get_author_meta(embed)) is not None and meta.service_name == "campagne_oroscopo" for embed in normalized)
    assert all((meta := get_footer_meta(embed)) is not None and meta.service_name == "campagne_oroscopo" for embed in normalized)

    async def _run() -> None:
        await finalize_embeds_author(normalized, author_service=None, default_service_name="unknown")
        assert all("UNKNOWN" not in str(embed.author.name or "").upper() for embed in normalized)

    asyncio.run(_run())


def test_execute_horoscope_service_uses_async_fetch_path() -> None:
    class _Channel(discord.abc.Messageable):
        async def _get_channel(self):
            return self

        async def send(self, *args, **kwargs):
            return SimpleNamespace(id=999)

    class _Bot:
        def get_channel(self, _id):
            return _Channel()

    async def _run() -> None:
        payload = _build_horoscope_payload()
        db = SimpleNamespace(
            upsert_campaign_content_message=AsyncMock(),
            update_campaign_content_next_run=AsyncMock(),
        )
        service = CampaignContentService(database=db, bot=_Bot(), ai_service=None)
        config = {"guild_id": "1", "channel_id": "2", "id": 4, "interval_minutes": 60, "sources_json": "[]"}

        with patch("app.services.campaign_content_service.fetch_horoscope_content_async", AsyncMock(return_value=payload)) as mocked_async_fetch:
            await service.execute_horoscope_service(config)

        mocked_async_fetch.assert_awaited_once()
        metadata = json.loads(db.upsert_campaign_content_message.await_args.kwargs["metadata_json"])
        assert metadata["used_model"] is None

    asyncio.run(_run())
