from app.services import campaign_content_fetchers as fetchers
from app.services.campaign_content_fetchers import _resolve_news_sources, classify_news_item, dedupe_news_items


def test_resolve_news_sources_accepts_display_labels_and_domains() -> None:
    resolved = _resolve_news_sources(["ansa.it", "repubblica.it", "https://www.corriere.it"])
    assert resolved == [
        "https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",
        "https://www.repubblica.it/rss/homepage/rss2.0.xml",
        "https://xml2.corriereobjects.it/rss/homepage.xml",
    ]


def test_resolve_news_sources_keeps_explicit_rss_url() -> None:
    rss = "https://www.ilpost.it/feed/"
    resolved = _resolve_news_sources([rss])
    assert resolved == [rss]


def test_fetch_news_content_keeps_multiple_selected_categories_ordered(monkeypatch) -> None:
    rss_xml = """
    <rss><channel>
        <item>
            <title>Cronaca e spettacolo insieme</title>
            <link>https://example.com/story</link>
            <description>Aggiornamento cronaca spettacolo.</description>
            <category>spettacolo</category>
        </item>
    </channel></rss>
    """

    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["cronaca", "spettacolo"])

    assert list(payload["categories"].keys()) == ["cronaca", "spettacolo"]
    assert len(payload["categories"]["cronaca"]) == 1
    assert len(payload["categories"]["spettacolo"]) == 1


def test_classify_news_item_detects_cronaca_without_literal_category() -> None:
    categories = classify_news_item(
        title="Incendio nella notte: due feriti e indagini della procura",
        description="Intervento di carabinieri e polizia dopo il rogo.",
        raw_categories=["TopNews"],
        source="ansa.it",
    )
    assert "cronaca" in categories


def test_classify_news_item_detects_viral_keywords() -> None:
    categories = classify_news_item(
        title="Video su TikTok: clip online diventa trend social",
        description="Meme e utenti scatenati su Instagram e web.",
        raw_categories=["Ultime"],
        source="fanpage.it",
    )
    assert "viral" in categories


def test_classify_news_item_maps_reality_and_polemica_to_trash_or_gossip() -> None:
    categories = classify_news_item(
        title="Reality nel caos: lite in diretta e polemica social",
        description="Siparietto trash tv con scandalo tra due vip.",
        raw_categories=["TV"],
        source="fanpage.it",
    )
    assert any(category in categories for category in ("trash", "gossip"))


def test_classify_news_item_detects_mondo_from_esteri_context() -> None:
    categories = classify_news_item(
        title="Esteri, tensione tra USA e Cina al vertice internazionale",
        description="Nuovo dossier su Ucraina e Nato.",
        raw_categories=["internazionale"],
        source="corriere.it",
    )
    assert "mondo" in categories


def test_fetch_news_content_multi_category_uses_requested_order(monkeypatch) -> None:
    rss_xml = """
    <rss><channel>
        <item><title>Incidente in centro: ferito grave</title><link>https://example.com/c1</link><description>Indaga la procura.</description><category>TopNews</category></item>
        <item><title>Video TikTok da record</title><link>https://example.com/v1</link><description>Trend social online.</description><category>Web</category></item>
        <item><title>Reality, lite e scandalo</title><link>https://example.com/t1</link><description>Polemica trash tv.</description><category>TV</category></item>
    </channel></rss>
    """
    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["cronaca", "viral", "trash"])

    assert list(payload["categories"].keys()) == ["cronaca", "viral", "trash"]
    assert payload["categories"]["cronaca"][0]["title"].startswith("Incidente")
    assert payload["categories"]["viral"][0]["title"].startswith("Video")
    assert payload["categories"]["trash"][0]["title"].startswith("Reality")


def test_fetch_news_content_with_realistic_feeds_does_not_require_literal_category(monkeypatch) -> None:
    feeds = {
        "https://ansa.mock/rss.xml": """
            <rss><channel>
                <item><title>Procura apre fascicolo dopo incendio</title><link>https://ansa.mock/c1</link><description>Carabinieri al lavoro.</description><category>TopNews</category></item>
            </channel></rss>
        """,
        "https://fanpage.mock/rss.xml": """
            <rss><channel>
                <item><title>Clip su Instagram diventa virale</title><link>https://fanpage.mock/v1</link><description>Trend web con milioni di utenti.</description><category>Attualità</category></item>
            </channel></rss>
        """,
        "https://corriere.mock/rss.xml": """
            <rss><channel>
                <item><title>Vertice internazionale su Gaza e Ucraina</title><link>https://corriere.mock/m1</link><description>Leader europei riuniti.</description><category>Primo piano</category></item>
            </channel></rss>
        """,
    }

    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: list(feeds.keys()))
    monkeypatch.setattr(fetchers, "_http_get", lambda url: feeds[url])

    payload = fetchers.fetch_news_content(["ansa", "fanpage", "corriere"], ["cronaca", "viral", "mondo"])

    assert "cronaca" in payload["categories"]
    assert "viral" in payload["categories"]
    assert "mondo" in payload["categories"]
    assert not payload["categories"].get("varie")


def test_fetch_news_content_fallbacks_to_varie_only_when_requested_categories_missing(monkeypatch) -> None:
    rss_xml = """
    <rss><channel>
        <item><title>Panoramica di giornata</title><link>https://example.com/g1</link><description>Aggiornamento generale.</description><category>TopNews</category></item>
    </channel></rss>
    """
    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["trash"])

    assert list(payload["categories"].keys()) == ["varie"]


def test_dedupe_news_items_still_works_for_news_classification_pipeline() -> None:
    items = [
        {"title": "Video social virale", "link": "https://example.com/x", "summary": "short", "category": "viral", "source": "ansa.it"},
        {"title": "Video social virale!", "link": "https://example.com/x?utm=1", "summary": "longer summary", "category": "viral", "source": "ansa.it"},
    ]
    deduped = dedupe_news_items(items)
    assert len(deduped) == 1
    assert deduped[0]["summary"] == "longer summary"
