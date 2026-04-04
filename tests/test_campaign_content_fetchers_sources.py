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


def test_fetch_news_content_classifies_by_keywords_without_literal_category_name(monkeypatch) -> None:
    rss_xml = """
    <rss><channel>
        <item>
            <title>Arresto dopo inseguimento in centro</title>
            <link>https://example.com/cronaca-1</link>
            <description>Intervento di polizia e carabinieri nella notte.</description>
            <category>TopNews</category>
        </item>
    </channel></rss>
    """

    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["cronaca"])

    assert list(payload["categories"].keys()) == ["cronaca"]
    assert payload["categories"]["cronaca"][0]["title"] == "Arresto dopo inseguimento in centro"


def test_fetch_news_content_matches_cronaca_viral_trash_without_exact_feed_category(monkeypatch) -> None:
    rss_xml = """
    <rss><channel>
        <item>
            <title>Tribunale: arresto dopo rapina in stazione</title>
            <link>https://example.com/c1</link>
            <description>Indagini della procura in corso.</description>
            <category>TopNews</category>
        </item>
        <item>
            <title>Video diventa virale su TikTok in poche ore</title>
            <link>https://example.com/v1</link>
            <description>Trend social esploso durante la notte.</description>
            <category>Web</category>
        </item>
        <item>
            <title>Gaffe imbarazzante al reality: pubblico senza parole</title>
            <link>https://example.com/t1</link>
            <description>Polemica social e siparietto trash in diretta.</description>
            <category>Entertainment</category>
        </item>
    </channel></rss>
    """

    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["cronaca", "viral", "trash"])

    assert list(payload["categories"].keys()) == ["cronaca", "viral", "trash"]
    assert len(payload["categories"]["cronaca"]) == 1
    assert len(payload["categories"]["viral"]) >= 1
    assert len(payload["categories"]["trash"]) == 1


def test_fetch_news_content_uses_varie_for_generic_feed_when_requested(monkeypatch) -> None:
    rss_xml = """
    <rss><channel>
        <item>
            <title>Aggiornamento della giornata</title>
            <link>https://example.com/generic</link>
            <description>Notizia generale senza segnali semantici forti.</description>
            <category>TopNews</category>
        </item>
    </channel></rss>
    """

    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["varie"])
    assert list(payload["categories"].keys()) == ["varie"]
    assert len(payload["categories"]["varie"]) == 1


def test_fetch_news_content_still_returns_empty_when_truly_no_items(monkeypatch) -> None:
    rss_xml = "<rss><channel></channel></rss>"
    monkeypatch.setattr(fetchers, "_resolve_news_sources", lambda _sources: ["https://example.com/feed.xml"])
    monkeypatch.setattr(fetchers, "_http_get", lambda _url: rss_xml)

    payload = fetchers.fetch_news_content(["ansa"], ["cronaca", "viral", "trash"])
    assert payload["categories"] == {}
