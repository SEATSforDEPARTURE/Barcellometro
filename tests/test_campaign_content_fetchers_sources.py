from app.services import campaign_content_fetchers as fetchers
from app.services.campaign_content_fetchers import _resolve_news_sources, classify_news_item


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


def test_classify_news_item_maps_cronaca_without_literal_category_word() -> None:
    categories = classify_news_item(
        title="Napoli, arrestato latitante dopo un blitz dei carabinieri",
        description="La procura indaga su una rapina con feriti.",
        raw_categories=["Top News"],
        source="https://www.ansa.it/sito/notizie/topnews/topnews_rss.xml",
    )
    assert "cronaca" in categories


def test_classify_news_item_maps_viral_world_and_trash_keywords() -> None:
    viral = classify_news_item(
        title="Video su TikTok: utenti e social impazziti per la clip",
        description="Il meme diventa virale sul web.",
        raw_categories=["News"],
        source="https://www.fanpage.it/feed/",
    )
    assert "viral" in viral

    trash = classify_news_item(
        title="Reality show tra polemiche e scandalo in diretta tv",
        description="Lite in studio e siparietto social.",
        raw_categories=["Spettacolo"],
        source="https://www.fanpage.it/feed/",
    )
    assert "trash" in trash or "gossip" in trash

    world = classify_news_item(
        title="Crisi internazionale: vertice tra USA, Europa e Ucraina",
        description="Gli esteri restano al centro del dibattito.",
        raw_categories=["Top News"],
        source="https://www.repubblica.it/rss/homepage/rss2.0.xml",
    )
    assert "mondo" in world


def test_fetch_news_content_single_category_uses_classification_not_literal_match(monkeypatch) -> None:
    rss_xml = """
    <rss><channel>
        <item>
            <title>Arrestato un latitante dopo un'indagine della procura</title>
            <link>https://example.com/cronaca</link>
            <description>I carabinieri hanno fermato il sospettato dopo la rapina.</description>
            <category>Top News</category>
        </item>
    </channel></rss>
    """
    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["cronaca"])
    assert list(payload["categories"].keys()) == ["cronaca"]
    assert payload["categories"]["cronaca"]


def test_fetch_news_content_multi_category_preserves_order_and_avoids_false_fallback(monkeypatch) -> None:
    rss_xml = """
    <rss><channel>
        <item>
            <title>Arrestato dopo una rapina: indagine della procura</title>
            <link>https://example.com/a</link>
            <description>Blitz dei carabinieri in città.</description>
            <category>Top News</category>
        </item>
        <item>
            <title>Video su TikTok: il web impazzisce per il meme</title>
            <link>https://example.com/b</link>
            <description>Clip virale su Instagram con migliaia di commenti.</description>
            <category>Social</category>
        </item>
        <item>
            <title>Reality in tv, polemica e scandalo in studio</title>
            <link>https://example.com/c</link>
            <description>Lite in diretta e siparietto che divide i social.</description>
            <category>Spettacolo</category>
        </item>
    </channel></rss>
    """
    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["cronaca", "viral", "trash"])
    assert list(payload["categories"].keys()) == ["cronaca", "viral", "trash"]
    assert all(payload["categories"][category] for category in ["cronaca", "viral", "trash"])
    assert payload["used_sources"] == ["https://example.com/feed.xml"]


def test_fetch_news_content_fallback_only_when_no_classifiable_items(monkeypatch) -> None:
    rss_xml = """
    <rss><channel>
        <item>
            <title>Aggiornamenti vari dalla redazione</title>
            <link>https://example.com/z</link>
            <description>Breve notizia generica senza elementi forti.</description>
            <category>Generale</category>
        </item>
    </channel></rss>
    """
    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["cronaca"])
    assert payload["categories"] == {}


def test_fetch_news_content_parses_pubdate_in_published_at(monkeypatch) -> None:
    rss_xml = """
    <rss><channel>
        <item>
            <title>Arrestato dopo un blitz</title>
            <link>https://example.com/date</link>
            <description>Cronaca locale.</description>
            <category>Cronaca</category>
            <pubDate>Thu, 09 Apr 2026 10:15:00 +0200</pubDate>
        </item>
    </channel></rss>
    """
    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["cronaca"])
    first = payload["categories"]["cronaca"][0]
    assert first["published_at"].endswith("+00:00")
