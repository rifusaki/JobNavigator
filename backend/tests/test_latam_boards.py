"""LatAm boards: Get on Board's JSON API, the Computrabajo and ElEmpleo HTML pages, and the wiring."""
from types import SimpleNamespace

import httpx
import pytest

from backend.models.db import Job, Search
from backend.scraper import search_modes as M
from backend.scraper._shared import job_boards
from backend.scraper.sources import latam


def _search(**kw):
    base = dict(name="t", search_mode="latam", search_term="desarrollador", location="", country="colombia",
                is_remote=None, hours_old=0, results_wanted=20, sources=["getonbrd"], company_filter=[])
    base.update(kw)
    return SimpleNamespace(**base)


class FakeSite:
    def __init__(self):
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if path == "/api/v0/search/jobs":
            page = int(request.url.params.get("page", "1"))
            jobs = {
                1: [_gob(1), _gob(2)],
                2: [_gob(3)],
            }.get(page, [])
            return httpx.Response(200, json={"data": jobs, "included": [
                {"id": "c1", "attributes": {"name": "Acme"}}]})
        if "computrabajo" in host:
            if path.startswith("/ofertas-de-trabajo/"):
                return httpx.Response(200, text=_COMPUTRABAJO_DETAIL)
            return httpx.Response(200, text=_COMPUTRABAJO_LISTING)
        if "elempleo" in host:
            if "trabajo" in request.url.params:
                return httpx.Response(200, text=_ELEMPLEO_LISTING)
            return httpx.Response(200, text=_ELEMPLEO_DETAIL)
        return httpx.Response(404, text="missing")


def _gob(i, published="2026-01-01"):
    return {"id": 100 + i, "attributes": {
        "title": f"Backend Engineer {i}", "remote": True, "remote_modality": "Remoto",
        "location": "Santiago", "description": "<p>Build <b>APIs</b></p>",
        "functions": "<p>Ship features</p>", "benefits": "<p>Health</p>",
        "min_salary": 50000, "max_salary": 70000, "salary_period": "ANNUAL",
        "salary_currency": "USD", "published_at": published,
        "company": {"id": "c1"}}, "links": {"public_url": f"/jobs/backend-engineer-{i}"}}


@pytest.fixture
def sites(monkeypatch):
    fake = FakeSite()
    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(fake), follow_redirects=True))
    return fake


_COMPUTRABAJO_LISTING = """
<article class="box_offer" data-id="1">
  <h2><a href="/ofertas-de-trabajo/oferta-de-trabajo-de-desarrollador-1234567890">Desarrollador Backend</a></h2>
  <div class="dFlex"><a href="/empresas/acme">Acme</a></div>
  <span class="ubicacion">Bogotá</span><time>Hoy</time>
</article>
<article class="box_offer" data-id="2">
  <h2><a href="/ofertas-de-trabajo/oferta-de-trabajo-de-analista-9876543210">Analista de datos</a></h2>
  <div class="dFlex"><a href="/empresas/beta">Beta</a></div>
  <span class="ubicacion">Medellín</span><time>Ayer</time>
</article>
"""

_COMPUTRABAJO_DETAIL = "<div class='box_detail'>" + ("Trabaja con nosotros en APIs y datos. " * 4) + "</div>"

_ELEMPLEO_LISTING = """
<div class="resultado"><h2><a href="/co/ofertas-empleo/desarrollador/123456">Desarrollador</a></h2>
  <span class="empresa">Acme</span><span class="ciudad">Medellín</span><time>Hoy</time></div>
"""

_ELEMPLEO_DETAIL = "<div class='descripcion-oferta'>" + ("Buscamos un desarrollador con experiencia. " * 4) + "</div>"


@pytest.mark.asyncio
async def test_getonbrd_lists_pages_and_maps_the_company(sites, monkeypatch):
    monkeypatch.setattr(latam, "_GETONBRD_PAGE", 2)
    async with job_boards.http_client() as client:
        rows = await latam._list_getonbrd(client, _search(), 10)

    assert [r["title"] for r in rows] == ["Backend Engineer 1", "Backend Engineer 2", "Backend Engineer 3"]
    first = rows[0]
    assert first["company"] == "Acme"
    assert first["url"] == "https://www.getonbrd.com/jobs/backend-engineer-1"
    assert first["location"] == "Santiago"
    assert first["arrangement"] == "remote"
    assert first["salary_min"] == 50000
    assert "Build APIs" in first["description"] and "Ship features" in first["description"]
    params = sites.requests[0].url.params
    assert params["query"] == "desarrollador" and params["expand"] == '["company"]'


@pytest.mark.asyncio
async def test_getonbrd_drops_old_jobs(monkeypatch):
    def only_old(request):
        return httpx.Response(200, json={"data": [_gob(1, published="2020-01-01")], "included": []})

    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(only_old), follow_redirects=True))
    async with job_boards.http_client() as client:
        rows = await latam._list_getonbrd(client, _search(hours_old=24), 10)
    assert rows == []


@pytest.mark.asyncio
async def test_computrabajo_uses_the_country_site_and_reads_cards(sites):
    async with job_boards.http_client() as client:
        rows = await latam._list_computrabajo(
            client, _search(country="argentina", location="Buenos Aires"), 10)

    request = sites.requests[0]
    assert request.url.host == "ar.computrabajo.com"
    assert request.url.path == "/trabajo-de-desarrollador"
    assert request.url.params["l"] == "Buenos Aires"
    assert [r["title"] for r in rows] == ["Desarrollador Backend", "Analista de datos"]
    assert rows[0]["company"] == "Acme" and rows[0]["location"] == "Bogotá"
    assert rows[0]["url"] == "https://ar.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-desarrollador-1234567890"


def test_spanish_relative_dates_become_iso():
    from datetime import datetime, timezone
    two_days = datetime.fromisoformat(latam._es_posted("Hace 2 días"))
    assert abs((datetime.now(timezone.utc) - two_days).total_seconds() - 2 * 86400) < 60
    assert latam._es_posted("Ayer") is not None
    assert latam._es_posted("Hoy") is not None
    assert latam._es_posted("Publicado hace un mes") is not None
    assert latam._es_posted("") is None


@pytest.mark.asyncio
async def test_computrabajo_relative_dates_apply_hours_old(sites):
    async with job_boards.http_client() as client:
        rows = await latam._list_computrabajo(client, _search(hours_old=1), 10)
    assert [r["title"] for r in rows] == ["Desarrollador Backend"]     # "Ayer" is older than 1 h


@pytest.mark.asyncio
async def test_computrabajo_city_filter_is_optional(sites):
    async with job_boards.http_client() as client:
        await latam._list_computrabajo(client, _search(country="atlantis"), 10)
    assert sites.requests[0].url.host == "co.computrabajo.com"      # unknown country falls back to Colombia
    assert "l" not in sites.requests[0].url.params


@pytest.mark.asyncio
async def test_computrabajo_detail_replaces_the_snippet(sites):
    row = {"url": "https://co.computrabajo.com/ofertas-de-trabajo/x", "description": "short"}
    async with job_boards.http_client() as client:
        await latam._detail_computrabajo(client, row)
    assert "Trabaja con nosotros en APIs y datos." in row["description"]


@pytest.mark.asyncio
async def test_elempleo_lists_and_reads_the_detail(sites):
    async with job_boards.http_client() as client:
        rows = await latam._list_elempleo(client, _search(location="Medellín"), 10)
        assert [r["title"] for r in rows] == ["Desarrollador"]
        assert rows[0]["company"] == "Acme" and rows[0]["location"] == "Medellín"
        request = sites.requests[0]
        assert request.url.params["trabajo"] == "desarrollador"
        assert request.url.params["ciudad"] == "Medellín"
        await latam._detail_elempleo(client, rows[0])
    assert "Buscamos un desarrollador con experiencia." in rows[0]["description"]


@pytest.mark.asyncio
async def test_latam_run_marks_board_links(sites, test_db, monkeypatch):
    async def fake_analyze(job, db=None, arrangement=None):
        job.work_arrangement = arrangement

    monkeypatch.setattr(job_boards, "analyze_inline", fake_analyze)
    monkeypatch.setattr("backend.activity.log_activity", lambda *a, **k: None)
    search = Search(name="t", search_mode="latam", search_term="desarrollador", results_wanted=10,
                    hours_old=0, sources=["getonbrd"], company_exclude=[])
    test_db.add(search)
    test_db.commit()

    result = await latam.run(search)

    assert result["error"] is None and result["source_breakdown"]["getonbrd"]["new"] == 2
    test_db.expire_all()
    job = test_db.query(Job).filter(Job.external_id != "").first()
    assert job.source == "getonbrd" and job.link_kind == "board"


def test_board_keys_match_the_mode_table():
    assert tuple(latam.BOARDS) == M.LATAM_BOARDS


def test_latam_mode_and_config_errors():
    assert M.default_sources("latam") == list(M.LATAM_BOARDS)
    assert M.config_error(Search(search_mode="latam")) == "LatAm boards needs a search term before it can run"
    assert M.config_error(Search(search_mode="latam", search_term="dev", sources=[])) == \
        "LatAm boards needs at least one board before it can run"
    assert M.config_error(Search(search_mode="latam", search_term="dev", sources=["getonbrd"])) is None
