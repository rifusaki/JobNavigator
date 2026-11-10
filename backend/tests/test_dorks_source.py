"""Search Dorks: the Serper and Brave clients, result parsing, details and account settings."""
import json

import httpx
import pytest

from backend.accounts.settings import set_setting
from backend.models.db import Search
from backend.scraper import search_modes as M
from backend.scraper._shared import job_boards
from backend.scraper.sources import dorks


def _search(**kw):
    base = dict(name="t", search_mode="dorks", search_term="site:linkedin.com/posts pasantía",
                hours_old=48, results_wanted=10, sources=[], company_filter=[])
    base.update(kw)
    return Search(**base)


def _fake(fn):
    return lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(fn), follow_redirects=True)


@pytest.mark.asyncio
async def test_serper_posts_the_query_with_its_time_filter(monkeypatch):
    seen = {}

    def site(request):
        seen["request"] = request
        return httpx.Response(200, json={"organic": [
            {"title": "Hiring pasantes at Acme", "link": "https://www.linkedin.com/posts/acme-1",
             "snippet": "Buscamos pasantes de ingeniería", "date": "2 days ago"},
            {"title": "Backend Engineer", "link": "https://jobs.acme.com/backend",
             "snippet": "Build APIs"},
        ]})

    monkeypatch.setattr(job_boards, "http_client", _fake(site))
    async with job_boards.http_client() as client:
        rows = await dorks._lister("serper", "secret")(client, _search(), 10)

    request = seen["request"]
    assert request.method == "POST" and str(request.url) == dorks._SERPER
    body = json.loads(request.content)
    assert body == {"q": "site:linkedin.com/posts pasantía", "num": 10, "tbs": "qdr:w"}
    assert request.headers["X-API-KEY"] == "secret"
    assert rows[0]["title"] == "Hiring pasantes at Acme"
    assert rows[0]["company"] == "LinkedIn Post"
    assert rows[0]["url"] == "https://www.linkedin.com/posts/acme-1"
    assert rows[0]["description"] == "Buscamos pasantes de ingeniería"
    assert rows[0]["posted"] == "2 days ago"
    assert rows[1]["company"] == "Acme"


@pytest.mark.asyncio
async def test_brave_gets_the_query_with_freshness_and_dedups_across_lines(monkeypatch):
    seen = []

    def site(request):
        seen.append(request)
        return httpx.Response(200, json={"web": {"results": [
            {"title": "Post", "url": "https://www.linkedin.com/posts/x", "description": "first"},
            {"title": "Post", "url": "https://www.linkedin.com/posts/x", "description": "duplicate"},
        ]}})

    monkeypatch.setattr(job_boards, "http_client", _fake(site))
    search = _search(search_term="first dork\nsecond dork", hours_old=720)
    async with job_boards.http_client() as client:
        rows = await dorks._lister("brave", "key")(client, search, 10)

    assert [r.url.path for r in seen] == [httpx.URL(dorks._BRAVE).path, httpx.URL(dorks._BRAVE).path]
    assert seen[0].headers["X-Subscription-Token"] == "key"
    assert seen[0].url.params["freshness"] == "pm"
    assert [r["url"] for r in rows] == ["https://www.linkedin.com/posts/x"]


@pytest.mark.asyncio
async def test_no_age_limit_omits_the_time_filter_and_clamps_brave(monkeypatch):
    seen = {}

    def site(request):
        seen["request"] = request
        return httpx.Response(200, json={"web": {"results": []}})

    monkeypatch.setattr(job_boards, "http_client", _fake(site))
    search = _search(hours_old=0)
    async with job_boards.http_client() as client:
        await dorks._lister("brave", "key")(client, search, 500)

    request = seen["request"]
    assert "freshness" not in request.url.params
    assert request.url.params["count"] == "20"


def test_company_uses_the_registrable_domain():
    assert dorks._company("Post", "https://jobs.acme.co.uk/x") == "Acme"
    assert dorks._company("Post", "https://acme.com.br/x") == "Acme"
    assert dorks._company("Post", "https://jobs.acme.com/x") == "Acme"


@pytest.mark.asyncio
async def test_missing_key_fails_loudly(monkeypatch):
    monkeypatch.setattr(job_boards, "http_client", _fake(lambda request: httpx.Response(500)))
    async with job_boards.http_client() as client:
        with pytest.raises(job_boards.BoardError, match="Serper API key"):
            await dorks._lister("serper", "")(client, _search(), 10)


@pytest.mark.asyncio
async def test_detail_keeps_the_longer_text(monkeypatch):
    page = "<html><body><script>bad()</script><main>" + ("Full job text. " * 10) + "</main></body></html>"
    monkeypatch.setattr(job_boards, "http_client", _fake(lambda request: httpx.Response(200, text=page)))
    row = {"url": "https://example.com/job", "description": "snippet"}
    async with job_boards.http_client() as client:
        await dorks._detail(client, row)
    assert "Full job text." in row["description"] and "bad()" not in row["description"]


def test_config_reads_the_account_settings(test_db):
    set_setting(test_db, "dork_search_provider", "brave")
    set_setting(test_db, "dork_search_api_key", "abc123")
    test_db.commit()
    assert dorks._config(test_db) == ("brave", "abc123")

    set_setting(test_db, "dork_search_provider", "altavista")
    test_db.commit()
    with pytest.raises(job_boards.BoardError, match="Unknown dork search provider"):
        dorks._config(test_db)


@pytest.mark.asyncio
async def test_preview_without_a_key_reports_the_setting(test_db):
    payload = await dorks.preview(_search(), test_db)
    assert payload["error"] == "Search Dorks needs a Serper API key (Settings › Search Dorks)"
    assert payload["source_errors"] == {"dorks": payload["error"]}
    assert payload["config"]["mode"] == "dorks"
    assert payload["detail_limit"] == job_boards.PREVIEW_DETAIL_LIMIT
    assert payload["jobs"] == [] and payload["duration"] == 0.0


def test_switching_a_search_to_dorks_pauses_it(api_client):
    sid = api_client.post("/api/searches", json={
        "name": "kw", "search_mode": "keyword", "search_term": "pm", "active": True}).json()["id"]
    assert api_client.get("/api/searches").json()[-1]["active"] is True
    r = api_client.patch(f"/api/searches/{sid}", json={"search_mode": "dorks"})
    assert r.status_code == 200
    assert r.json()["active"] is False


def test_dorks_mode_is_paid_and_needs_a_term():
    mode = M.SEARCH_MODES["dorks"]
    assert (mode.paid, mode.needs_term, mode.background_test) == (True, True, True)
    assert M.config_error(Search(search_mode="dorks")) == "Search Dorks needs a search term before it can run"
    assert M.config_error(Search(search_mode="dorks", search_term="site:linkedin.com/posts x")) is None
