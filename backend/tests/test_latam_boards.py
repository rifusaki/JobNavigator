"""LatAm boards: Get on Board's JSON API, the Computrabajo and ElEmpleo HTML pages, and the wiring."""
import json
from datetime import datetime, timezone
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


def _ts(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


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
            if path.startswith("/co/ofertas-trabajo/"):
                return httpx.Response(200, text=_ELEMPLEO_DETAIL)
            return httpx.Response(200, text=_ELEMPLEO_LISTING)
        return httpx.Response(404, text="missing")


def _gob(i, published=1794328465, countries=None, location=None, remote_modality="Remoto", remote=True):
    attrs = {
        "title": f"Backend Engineer {i}", "remote": remote, "remote_modality": remote_modality,
        "countries": countries if countries is not None else ["Chile"],
        "description": "<p>Build <b>APIs</b></p>",
        "functions": "<p>Ship features</p>", "benefits": "<p>Health</p>",
        "min_salary": 50000, "max_salary": 70000, "salary_period": "ANNUAL",
        "salary_currency": "USD", "published_at": published,
        "company": {"data": {"id": "c1", "attributes": {"name": "Acme"}}},
    }
    if location is not None:
        attrs["location"] = location
    return {"id": 100 + i, "attributes": attrs,
            "links": {"public_url": f"/jobs/backend-engineer-{i}"}}


@pytest.fixture
def sites(monkeypatch):
    fake = FakeSite()
    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(fake), follow_redirects=True))
    return fake


_COMPUTRABAJO_LISTING = """
<article class="box_offer" data-id="1">
  <h2 class="fs18 fwB prB"><a class="js-o-link fc_base"
      href="/ofertas-de-trabajo/oferta-de-trabajo-de-desarrollador-1234567890">Desarrollador Backend</a></h2>
  <p class="dFlex vm_fx fs16 fc_base mt5"><a class="fc_base t_ellipsis"
      href="https://co.computrabajo.com/acme" offer-grid-article-company-url="">Acme</a></p>
  <p class="fs16 fc_base mt5"><span class="mr10">Bogotá, D.C., Bogotá, D.C.</span></p>
  <div class="fs13 mt15"><span class="dIB mr10">$ 5.000.000,00 (Mensual)</span>
    <span class="dIB mr10">Remoto</span></div>
  <p class="fs13 fc_aux mt15">Hoy</p>
</article>
<article class="box_offer" data-id="2">
  <h2 class="fs18 fwB prB"><a class="js-o-link fc_base"
      href="/ofertas-de-trabajo/oferta-de-trabajo-de-analista-9876543210">Analista de datos</a></h2>
  <p class="dFlex vm_fx fs16 fc_base mt5"><span class="stars">4.6</span>
    <a class="fc_base t_ellipsis" href="https://co.computrabajo.com/empresa">Importante empresa del sector</a></p>
  <p class="fs16 fc_base mt5"><span class="mr10">Medellín, Antioquia</span></p>
  <p class="fs13 fc_aux mt15">Ayer</p>
</article>
"""

_COMPUTRABAJO_DETAIL = """
<div class="box_detail fl w100_m">
  <div div-link="oferta">
    <h2>Descripción de la oferta</h2>
    <p>Trabaja con nosotros en APIs y datos. OFERTA LABORAL ANALISTA DE DATOS</p>
  </div>
</div>
"""

_ELEMPLEO_LISTING = """
<div class="col-md-12 result-item">
  <div class="js-area-bind" data-ga4-offerdata='{"title":"Desarrollador","company":"Acme","location":"Medellín"}'>
    <h2><a class="js-offer-title" href="/co/ofertas-trabajo/desarrollador-123456">Desarrollador</a></h2>
    <span class="js-offer-company">Acme</span>
    <span class="js-offer-city">Medellín</span>
    <span class="js-offer-date">Hoy</span>
    <div class="js-work-modality">Hibrido</div>
  </div>
</div>
"""

_ELEMPLEO_DETAIL = """
<div class="description-block e-container-keywords">
  <h2>Descripción del cargo</h2>
  <p>Buscamos un desarrollador con experiencia. Buscamos un desarrollador con experiencia.</p>
</div>
"""

# The current search page hands its own API: the request params as JSON and the
# anti-forgery token the findbyfilter endpoint wants. The card stays in the HTML,
# so the fallback tests read the same page.
_ELEMPLEO_API_LISTING = """
<div class="js-search-api-token">
  <input name="__RequestVerificationToken" value="tok-123">
</div>
<div data-request-params='{"what":"desarrollador","pageIndex":1,"pageSize":20,"sortBy":"10"}'></div>
<div class="col-md-12 result-item">
  <div class="js-area-bind" data-ga4-offerdata='{"title":"Desarrollador","company":"Acme","location":"Medellín"}'>
    <h2><a class="js-offer-title" href="/co/ofertas-trabajo/desarrollador-123456">Desarrollador</a></h2>
    <span class="js-offer-company">Acme</span>
    <span class="js-offer-city">Medellín</span>
    <span class="js-offer-date">Hoy</span>
    <div class="js-work-modality">Hibrido</div>
  </div>
</div>
"""


def _ee(i, info="Hoy", remote=False, hybrid=False, modality="Presencial"):
    """One findbyfilter result item, the way the newest-first API answers."""
    return {
        "title": f"Desarrollador {i}", "companyName": "Acme",
        "jobOfferUrl": f"/co/ofertas-trabajo/desarrollador-{i}?trabajo=q",
        "city": "Bogotá", "description": "<p>Construye <b>APIs</b></p>",
        "idworkmodalitytxt": modality, "isRemote": remote, "isHybrid": hybrid,
        "publishDateInfo": info, "publishDate": "2026-01-01T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_getonbrd_lists_pages_and_maps_the_company(sites, monkeypatch):
    monkeypatch.setattr(latam, "_GETONBRD_PAGE", 2)
    async with job_boards.http_client() as client:
        rows = await latam._list_getonbrd(client, _search(), 10)

    assert [r["title"] for r in rows] == ["Backend Engineer 1", "Backend Engineer 2", "Backend Engineer 3"]
    first = rows[0]
    assert first["company"] == "Acme"
    assert first["url"] == "https://www.getonbrd.com/jobs/backend-engineer-1"
    assert first["location"] == "Chile"
    assert first["countries"] == ["Chile"]
    assert first["arrangement"] == "remote"
    assert first["salary_min"] == 50000
    assert first["posted"].startswith("2026-") or first["posted"].startswith("2027-")
    assert "Build APIs" in first["description"] and "Ship features" in first["description"]
    params = sites.requests[0].url.params
    assert params["query"] == "desarrollador" and params["expand"] == '["company"]'


@pytest.mark.asyncio
async def test_getonbrd_drops_old_jobs(monkeypatch):
    def only_old(request):
        return httpx.Response(200, json={"data": [_gob(1, published=_ts("2020-01-01"))], "included": []})

    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(only_old), follow_redirects=True))
    async with job_boards.http_client() as client:
        rows = await latam._list_getonbrd(client, _search(hours_old=24), 10)
    assert rows == []


@pytest.mark.asyncio
async def test_getonbrd_collects_page_two_after_an_old_job_on_page_one(monkeypatch):
    """The API sorts by relevance, so page 1 mixes old and new postings; one old
    row must not end the walk before page 2's fresh jobs are read."""
    monkeypatch.setattr(latam, "_GETONBRD_PAGE", 2)
    fresh_ts = int(datetime.now(timezone.utc).timestamp())

    def mixed(request):
        page = int(request.url.params.get("page", "1"))
        jobs = {1: [_gob(1, published=_ts("2020-01-01")), _gob(2, published=fresh_ts)],
                2: [_gob(3, published=fresh_ts)]}.get(page, [])
        return httpx.Response(200, json={"data": jobs, "included": []})

    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(mixed), follow_redirects=True))
    async with job_boards.http_client() as client:
        rows = await latam._list_getonbrd(client, _search(hours_old=24), 10)
    assert [r["title"] for r in rows] == ["Backend Engineer 2", "Backend Engineer 3"]


def test_getonbrd_country_filter_drops_other_countries():
    chile = job_boards.make_row(title="Backend Engineer", location="Chile", countries=["Chile"])
    chile["source"] = "getonbrd"
    colombia = job_boards.make_row(title="Backend Engineer", location="Colombia", countries=["Colombia"])
    colombia["source"] = "getonbrd"
    search = _search(country="colombia")
    assert job_boards._rejection(chile, search, latam.BOARDS, [], [], set(), set()) == "Not open to Colombia"
    assert job_boards._rejection(colombia, search, latam.BOARDS, [], [], set(), set()) is None


def test_getonbrd_country_filter_falls_back_to_location_suffix():
    search = _search(country="", location="Bogota, Colombia")
    chile = job_boards.make_row(title="Backend Engineer", location="Chile", countries=["Chile"])
    chile["source"] = "getonbrd"
    colombia = job_boards.make_row(title="Backend Engineer", location="Colombia", countries=["Colombia"])
    colombia["source"] = "getonbrd"
    assert job_boards._rejection(chile, search, latam.BOARDS, [], [], set(), set()) == "Not open to Colombia"
    assert job_boards._rejection(colombia, search, latam.BOARDS, [], [], set(), set()) is None


def test_getonbrd_keeps_city_and_hybrid_modality():
    row = latam._getonbrd_row(_gob(1, location="Santiago", remote_modality="hybrid_local"), {})
    assert row["location"] == "Santiago, Chile"
    assert row["arrangement"] == "hybrid"


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
    assert rows[0]["company"] == "Acme" and "Bogotá" in rows[0]["location"]
    assert rows[0]["arrangement"] == "remote"
    assert rows[1]["company"] == "Importante empresa del sector"
    assert rows[0]["url"] == "https://ar.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-desarrollador-1234567890"


def test_spanish_relative_dates_become_iso():
    two_days = datetime.fromisoformat(latam._es_posted("Hace 2 días"))
    assert abs((datetime.now(timezone.utc) - two_days).total_seconds() - 2 * 86400) < 60
    assert latam._es_posted("Ayer") is not None
    assert latam._es_posted("Hoy") is not None
    assert latam._es_posted("Publicado hace un mes") is not None
    two_months = datetime.fromisoformat(latam._es_posted("Hace 2 meses"))
    assert abs((datetime.now(timezone.utc) - two_months).total_seconds() - 60 * 86400) < 60
    assert latam._es_posted("") is None


@pytest.mark.asyncio
async def test_computrabajo_relative_dates_apply_hours_old(sites):
    async with job_boards.http_client() as client:
        rows = await latam._list_computrabajo(client, _search(hours_old=1), 10)
    assert [r["title"] for r in rows] == ["Desarrollador Backend"]     # "Ayer" is older than 1 h


def test_a_coarse_day_old_date_survives_hours_old_24():
    """`_es_posted("Ayer")` stamps now - 24 h and too_old() reads the clock again a
    moment later; without the drift grace, hours_old=24 always dropped "Ayer"."""
    for text in ("Ayer", "Hace 1 día"):
        row = job_boards.make_row(title="Analista de datos", posted=latam._es_posted(text))
        assert job_boards.too_old(row, 24) is None
        assert job_boards.too_old(row, 1) is not None


@pytest.mark.asyncio
async def test_computrabajo_keeps_ayer_at_hours_old_24(sites):
    async with job_boards.http_client() as client:
        rows = await latam._list_computrabajo(client, _search(hours_old=24), 10)
    assert [r["title"] for r in rows] == ["Desarrollador Backend", "Analista de datos"]


@pytest.mark.asyncio
async def test_computrabajo_city_filter_is_optional(sites):
    async with job_boards.http_client() as client:
        await latam._list_computrabajo(client, _search(country="atlantis"), 10)
    assert sites.requests[0].url.host == "co.computrabajo.com"      # unknown country falls back to Colombia
    assert "l" not in sites.requests[0].url.params


def test_city_match_ignores_accents():
    search = _search(location="Bogota")
    bogota = job_boards.make_row(title="Analista de datos", location="Bogotá, D.C., Bogotá, D.C.")
    bogota["source"] = "computrabajo"
    medellin = job_boards.make_row(title="Analista de datos", location="Medellín, Antioquia")
    medellin["source"] = "computrabajo"
    assert job_boards._rejection(bogota, search, latam.BOARDS, [], [], set(), set()) is None
    assert job_boards._rejection(medellin, search, latam.BOARDS, [], [], set(), set()) == "Not in Bogota"


@pytest.mark.asyncio
async def test_computrabajo_detail_replaces_the_snippet(sites):
    row = {"url": "https://co.computrabajo.com/ofertas-de-trabajo/x", "description": "short"}
    async with job_boards.http_client() as client:
        await latam._detail_computrabajo(client, row)
    assert "Trabaja con nosotros en APIs y datos." in row["description"]


@pytest.mark.asyncio
async def test_elempleo_empty_search_is_not_a_board_error(monkeypatch):
    def missing(request):
        return httpx.Response(404, text="missing")

    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(missing), follow_redirects=True))
    async with job_boards.http_client() as client:
        assert await latam._list_elempleo(client, _search(), 10) == []


@pytest.mark.asyncio
async def test_elempleo_lists_pages_and_reads_the_detail(sites):
    async with job_boards.http_client() as client:
        rows = await latam._list_elempleo(client, _search(location="Medellín"), 10)
        assert [r["title"] for r in rows] == ["Desarrollador"]
        assert rows[0]["company"] == "Acme" and rows[0]["location"] == "Medellín"
        assert rows[0]["arrangement"] == "hybrid"
        request = sites.requests[0]
        assert request.url.path == "/co/ofertas-empleo/trabajo-desarrollador"
        assert request.url.params["pagina"] == "0"
        assert request.url.params["ciudad"] == "Medellín"
        await latam._detail_elempleo(client, rows[0])
    assert "Buscamos un desarrollador con experiencia." in rows[0]["description"]


@pytest.mark.asyncio
async def test_elempleo_api_sorts_newest_first_and_maps_rows(monkeypatch):
    monkeypatch.setattr(latam, "_ELEMPLEO_PAGE_SIZE", 2)
    posts = []

    def site(request):
        if request.method == "POST":
            posts.append(request)
            items = {1: [_ee(1), _ee(2, hybrid=True)], 2: [_ee(3, remote=True)]}.get(
                json.loads(request.content)["pageIndex"], [])
            return httpx.Response(200, json={"results": items})
        return httpx.Response(200, text=_ELEMPLEO_API_LISTING)

    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(site), follow_redirects=True))
    async with job_boards.http_client() as client:
        rows = await latam._list_elempleo(client, _search(hours_old=24), 10)

    assert [r["title"] for r in rows] == ["Desarrollador 1", "Desarrollador 2", "Desarrollador 3"]
    first = rows[0]
    assert first["company"] == "Acme"
    assert first["url"] == "https://www.elempleo.com/co/ofertas-trabajo/desarrollador-1"
    assert first["location"] == "Bogotá"
    assert "Construye APIs" in first["description"]
    assert [r["arrangement"] for r in rows] == ["onsite", "hybrid", "remote"]
    # publishDateInfo ("Hoy") wins over publishDate (midnight UTC)
    age_s = (datetime.now(timezone.utc) - datetime.fromisoformat(first["posted"])).total_seconds()
    assert age_s < 60
    body = json.loads(posts[0].content)
    assert body["sortBy"] == "PublishDate_Desc" and body["sortExpression"] == "PublishDate_Desc"
    assert body["pageIndex"] == 1 and body["pageSize"] == 2
    assert body["what"] == "desarrollador"          # the page's own search params ride along
    assert posts[0].headers["__RequestVerificationToken"] == "tok-123"
    assert posts[0].headers["Content-Type"] == "application/json; charset=utf-8"


@pytest.mark.asyncio
async def test_elempleo_api_falls_back_to_the_html_cards_when_the_post_fails(monkeypatch):
    def site(request):
        if request.method == "POST":
            return httpx.Response(500, text="boom")
        return httpx.Response(200, text=_ELEMPLEO_API_LISTING)

    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(site), follow_redirects=True))
    async with job_boards.http_client() as client:
        rows = await latam._list_elempleo(client, _search(), 10)
    assert [r["title"] for r in rows] == ["Desarrollador"]      # the HTML card, not a board error


@pytest.mark.asyncio
async def test_elempleo_api_falls_back_to_the_html_cards_when_the_post_is_not_json(monkeypatch):
    def site(request):
        if request.method == "POST":
            return httpx.Response(200, text="<html>not json</html>")
        return httpx.Response(200, text=_ELEMPLEO_API_LISTING)

    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(site), follow_redirects=True))
    async with job_boards.http_client() as client:
        rows = await latam._list_elempleo(client, _search(), 10)
    assert [r["title"] for r in rows] == ["Desarrollador"]


@pytest.mark.asyncio
async def test_elempleo_api_stops_when_a_full_page_turns_old(monkeypatch):
    monkeypatch.setattr(latam, "_ELEMPLEO_PAGE_SIZE", 2)
    posts = []

    def site(request):
        if request.method == "POST":
            posts.append(request)
            items = {1: [_ee(1), _ee(2, info="Hace 2 días")],               # one old row among fresh ones
                      2: [_ee(3, info="Hace 2 días"), _ee(4, info="Hace 2 días")]}.get(
                json.loads(request.content)["pageIndex"], [])
            return httpx.Response(200, json={"results": items})
        return httpx.Response(200, text=_ELEMPLEO_API_LISTING)

    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(site), follow_redirects=True))
    async with job_boards.http_client() as client:
        rows = await latam._list_elempleo(client, _search(hours_old=24), 10)

    assert [r["title"] for r in rows] == ["Desarrollador 1"]
    # page 2 was reached (a single old row is not a stop); an all-old page after
    # fresh ones is, so page 3 is never asked for
    assert len(posts) == 2


@pytest.mark.asyncio
async def test_elempleo_api_walks_past_a_page_of_pinned_old_offers(monkeypatch):
    monkeypatch.setattr(latam, "_ELEMPLEO_PAGE_SIZE", 2)

    def site(request):
        if request.method == "POST":
            items = {1: [_ee(1, info="Hace 2 días"), _ee(2, info="Hace 2 días")],   # pinned, all old
                      2: [_ee(3)]}.get(json.loads(request.content)["pageIndex"], [])  # short page, fresh
            return httpx.Response(200, json={"results": items})
        return httpx.Response(200, text=_ELEMPLEO_API_LISTING)

    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(site), follow_redirects=True))
    async with job_boards.http_client() as client:
        rows = await latam._list_elempleo(client, _search(hours_old=24), 10)
    assert [r["title"] for r in rows] == ["Desarrollador 3"]


@pytest.mark.asyncio
async def test_elempleo_api_dedups_pinned_rows_across_pages(monkeypatch):
    monkeypatch.setattr(latam, "_ELEMPLEO_PAGE_SIZE", 2)

    def site(request):
        if request.method == "POST":
            items = {1: [_ee(1), _ee(2)], 2: [_ee(1), _ee(3)]}.get(
                json.loads(request.content)["pageIndex"], [])
            return httpx.Response(200, json={"results": items})
        return httpx.Response(200, text=_ELEMPLEO_API_LISTING)

    monkeypatch.setattr(job_boards, "http_client", lambda mounts=None: httpx.AsyncClient(
        transport=httpx.MockTransport(site), follow_redirects=True))
    async with job_boards.http_client() as client:
        rows = await latam._list_elempleo(client, _search(hours_old=24), 10)
    assert [r["title"] for r in rows] == ["Desarrollador 1", "Desarrollador 2", "Desarrollador 3"]


@pytest.mark.asyncio
async def test_latam_run_marks_board_links(sites, test_db, monkeypatch):
    async def fake_analyze(job, db=None, arrangement=None):
        job.work_arrangement = arrangement

    monkeypatch.setattr(job_boards, "analyze_inline", fake_analyze)
    monkeypatch.setattr("backend.activity.log_activity", lambda *a, **k: None)
    search = Search(name="t", search_mode="latam", search_term="desarrollador", country="chile",
                    results_wanted=10, hours_old=0, sources=["getonbrd"], company_exclude=[])
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
