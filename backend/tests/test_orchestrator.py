"""Tests for orchestrator.py — entry-point dispatch."""
import pytest
from unittest.mock import AsyncMock, MagicMock


def test_orchestrator_exposes_run_all():
    from backend.scraper import orchestrator
    assert hasattr(orchestrator, "run_all")


def test_orchestrator_exposes_run_search():
    from backend.scraper import orchestrator
    assert hasattr(orchestrator, "run_search")


def test_orchestrator_exposes_run_company():
    from backend.scraper import orchestrator
    assert hasattr(orchestrator, "run_company")


@pytest.mark.asyncio
async def test_run_search_dispatches_keyword(monkeypatch):
    """search_mode='keyword' routes to sources.jobspy."""
    called = {"src": None}

    async def fake_jobspy(search, proxy_url=None):
        called["src"] = "jobspy"
        return {"jobs_found": 0, "new_jobs": 0, "error": None, "duration": 0}

    monkeypatch.setattr("backend.scraper.sources.jobspy.run", fake_jobspy)

    class FakeSearch:
        id = "s-1"
        search_mode = "keyword"

    from backend.scraper.orchestrator import run_search
    await run_search(FakeSearch())
    assert called["src"] == "jobspy"


@pytest.mark.asyncio
async def test_run_search_rejects_legacy_url_mode():
    """The legacy `url` search mode was removed — it is now an unknown mode."""
    class FakeSearch:
        id = "s-1"; search_mode = "url"; direct_url = "https://example.com/jobs"

    from backend.scraper import orchestrator
    assert orchestrator._search_mode_is_valid(FakeSearch()) is False
    with pytest.raises(ValueError):
        await orchestrator.run_search(FakeSearch())


@pytest.mark.asyncio
async def test_run_search_dispatches_levelsfyi(monkeypatch):
    called = {"src": None}
    async def fake_levels(search):
        called["src"] = "levels_fyi"; return {}
    monkeypatch.setattr("backend.scraper.sources.levelsfyi.run", fake_levels)

    class FakeSearch:
        id = "s-1"; search_mode = "levels_fyi"

    from backend.scraper.orchestrator import run_search
    await run_search(FakeSearch())
    assert called["src"] == "levels_fyi"


@pytest.mark.asyncio
async def test_run_search_dispatches_linkedin_personal(monkeypatch):
    called = {"src": None}
    async def fake_li(search):
        called["src"] = "linkedin_personal"; return {}
    monkeypatch.setattr("backend.scraper.sources.linkedin_personal.run", fake_li)

    class FakeSearch:
        id = "s-1"; search_mode = "linkedin_personal"

    from backend.scraper.orchestrator import run_search
    await run_search(FakeSearch())
    assert called["src"] == "linkedin_personal"


@pytest.mark.asyncio
async def test_run_search_dispatches_jobright(monkeypatch):
    called = {"src": None}
    async def fake_jr(search):
        called["src"] = "jobright"; return {}
    monkeypatch.setattr("backend.scraper.sources.jobright.run", fake_jr)

    class FakeSearch:
        id = "s-1"; search_mode = "jobright"

    from backend.scraper.orchestrator import run_search
    await run_search(FakeSearch())
    assert called["src"] == "jobright"


@pytest.mark.asyncio
async def test_run_search_linkedin_extension_is_noop(monkeypatch):
    """linkedin_extension has no scraper — jobs arrive via POST /api/jobs/linkedin-import."""
    class FakeSearch:
        id = "s-1"; search_mode = "linkedin_extension"

    from backend.scraper.orchestrator import run_search
    result = await run_search(FakeSearch())
    # Should return without raising; result should indicate no scrape happened
    assert result is not None
    assert result.get("jobs_found", 0) == 0


@pytest.mark.asyncio
async def test_run_search_raises_on_unknown_mode():
    class FakeSearch:
        id = "s-1"; search_mode = "unknown_mode"

    from backend.scraper.orchestrator import run_search
    with pytest.raises(ValueError):
        await run_search(FakeSearch())


@pytest.mark.asyncio
async def test_run_company_delegates_to_company_pages(monkeypatch):
    called = {"name": None}

    async def fake_scrape(company, shared_browser=None):
        called["name"] = company.name
        return {"jobs_found": 0, "new_jobs": 0}

    monkeypatch.setattr(
        "backend.scraper.sources.company_pages.scrape_single_career_page",
        fake_scrape,
    )

    class FakeCompany:
        name = "Acme"
        scrape_urls = ["https://x.com"]

    from backend.scraper.orchestrator import run_company
    await run_company(FakeCompany())
    assert called["name"] == "Acme"


def test_target_priority_mapping():
    from backend.scraper.orchestrator import _target_priority, _SEARCH_MODE_PRIORITY
    from backend.scraper.targets import Target

    class FakeSearch:
        def __init__(self, mode):
            self.search_mode = mode

    assert _target_priority(Target(key=("dorks",), subscribers=[FakeSearch("dorks")])) == 10
    assert _target_priority(Target(key=("latam",), subscribers=[FakeSearch("latam")])) == 20
    assert _target_priority(Target(key=("eightfold",), subscribers=[FakeSearch("eightfold")])) == 30
    assert _target_priority(Target(key=("keyword",), subscribers=[FakeSearch("keyword")])) == 40
    assert _target_priority(Target(key=("company",), subscribers=[FakeSearch("company")])) == 50
    assert _target_priority(Target(key=("other",), subscribers=[FakeSearch("other")])) == 50
    assert _target_priority(Target(key=("linkedin_personal",), subscribers=[FakeSearch("linkedin_personal")])) == 90

    # Fallback to key when subscribers are empty or search_mode missing
    assert _target_priority(Target(key=("dorks", "own", "1"), subscribers=[])) == 10
    assert _target_priority(Target(key=("latam",), subscribers=[FakeSearch(None)])) == 20
    assert _target_priority(None) == 50


def test_target_priority_stable_sorting():
    from backend.scraper.orchestrator import _target_priority
    from backend.scraper.targets import Target

    class FakeSearch:
        def __init__(self, mode, name):
            self.search_mode = mode
            self.name = name

    t_li1 = Target(key=("linkedin_personal", "1"), subscribers=[FakeSearch("linkedin_personal", "li-1")])
    t_kw1 = Target(key=("keyword", "1"), subscribers=[FakeSearch("keyword", "kw-1")])
    t_dorks = Target(key=("dorks", "1"), subscribers=[FakeSearch("dorks", "dorks-1")])
    t_latam = Target(key=("latam", "1"), subscribers=[FakeSearch("latam", "latam-1")])
    t_kw2 = Target(key=("keyword", "2"), subscribers=[FakeSearch("keyword", "kw-2")])
    t_li2 = Target(key=("linkedin_personal", "2"), subscribers=[FakeSearch("linkedin_personal", "li-2")])

    targets = [t_li1, t_kw1, t_dorks, t_latam, t_kw2, t_li2]
    targets.sort(key=_target_priority)

    # Expected order: dorks (10), latam (20), kw-1 (40), kw-2 (40), li-1 (90), li-2 (90)
    # Notice stable preservation of kw-1 before kw-2, and li-1 before li-2
    names = [t.subscribers[0].name for t in targets]
    assert names == ["dorks-1", "latam-1", "kw-1", "kw-2", "li-1", "li-2"]

