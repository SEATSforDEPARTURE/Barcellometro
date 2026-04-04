from app.services import campaign_content_fetchers as fetchers
from app.services.campaign_content_fetchers import _resolve_news_sources


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
