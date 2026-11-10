"""Tests for ats/eightfold.py — detection, custom domains, pagination, filters, keys."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.scraper._shared.postings import posting_key


def _response(payload, status=200, url="https://mercadolibre.eightfold.ai/api/apply/v2/jobs"):
    resp = MagicMock()
    resp.status_code = status
    resp.json = MagicMock(return_value=payload)
    resp.text = json.dumps(payload)
    resp.url = url
    return resp


def _client(responses):
    client = MagicMock()
    client.get = AsyncMock(side_effect=responses)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _position(pid, title, location="Bogotá, Colombia", arrangement="onsite"):
    return {
        "id": pid,
        "name": title,
        "location": location,
        "locations": [location, "Medellín, Colombia"],
        "work_location_option": arrangement,
        "canonicalPositionUrl": f"https://careers-meli.mercadolibre.com/es/job/{pid}",
    }


def test_is_eightfold_detects_tenant_portals():
    from backend.scraper.ats.eightfold import is_eightfold
    assert is_eightfold("https://paypal.eightfold.ai/careers")
    assert is_eightfold("https://netflix.eightfold.ai/careers?pid=790314668577")


def test_is_eightfold_detects_custom_wrappers():
    from backend.scraper.ats.eightfold import is_eightfold
    assert is_eightfold("https://careers-meli.mercadolibre.com/es")
    assert is_eightfold("https://explore.jobs.netflix.net/careers")


def test_is_eightfold_rejects_other_boards_and_path_injection():
    from backend.scraper.ats.eightfold import is_eightfold
    assert not is_eightfold("https://jobs.lever.co/acme")
    assert not is_eightfold("https://attacker.com/?url=eightfold.ai")


def test_bare_eightfold_host_is_not_a_tenant_board():
    from backend.scraper.ats.eightfold import is_eightfold, target
    assert not is_eightfold("https://eightfold.ai/careers")
    assert target("https://eightfold.ai/careers") is None
    assert posting_key("https://eightfold.ai/careers?pid=1234567890") is None


def test_target_resolves_custom_host_and_tenant_domain():
    from backend.scraper.ats.eightfold import target
    assert target("https://careers-meli.mercadolibre.com/es") == (
        "mercadolibre.eightfold.ai", "mercadolibre.com")
    assert target("https://paypal.eightfold.ai/careers") == ("paypal.eightfold.ai", "paypal.com")
    assert target("https://paypal.eightfold.ai/careers?domain=paypal.com") == (
        "paypal.eightfold.ai", "paypal.com")


def test_target_rejects_non_eightfold():
    from backend.scraper.ats.eightfold import target
    assert target("https://jobs.lever.co/acme") is None


def test_posting_id_reads_pid_and_path_forms():
    from backend.scraper.ats.eightfold import posting_id
    assert posting_id("https://paypal.eightfold.ai/careers?pid=274922421537") == "274922421537"
    assert posting_id("https://paypal.eightfold.ai/careers/job/274908167038") == "274908167038"
    assert posting_id("https://careers-meli.mercadolibre.com/es/job/12345") == "12345"
    assert posting_id("https://paypal.eightfold.ai/careers") is None


@pytest.mark.asyncio
async def test_scrape_paginates_and_forwards_filters(monkeypatch):
    first = {"positions": [_position("1", "Senior Product Manager"),
                           _position("2", "Staff Software Engineer", arrangement="remote")]}
    second = {"positions": [_position("3", "Data Analyst Internship")]}
    client = _client([_response(first), _response(second)])

    import backend.scraper.ats.eightfold as eightfold
    monkeypatch.setattr(eightfold, "_PAGE", 2)
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)

    jobs = await eightfold.scrape(
        "https://careers-meli.mercadolibre.com/es?location=Colombia&q=pasantia")

    assert [j["title"] for j in jobs] == [
        "Senior Product Manager", "Staff Software Engineer", "Data Analyst Internship"]
    assert jobs[0]["url"] == "https://careers-meli.mercadolibre.com/es/job/1"
    assert jobs[0]["location"] == "Bogotá, Colombia"
    assert jobs[0]["locations"] == ["Bogotá, Colombia", "Medellín, Colombia"]
    assert jobs[0]["arrangement"] == "onsite"
    assert jobs[1]["arrangement"] == "remote"

    first_params = client.get.call_args_list[0].kwargs["params"]
    assert first_params["domain"] == "mercadolibre.com"
    assert first_params["num"] == "2"
    assert first_params["start"] == "0"
    assert first_params["location"] == "Colombia"
    assert first_params["q"] == "pasantia"
    assert client.get.call_args_list[1].kwargs["params"]["start"] == "2"


@pytest.mark.asyncio
async def test_scrape_forwards_country_and_query_aliases(monkeypatch):
    client = _client([_response({"positions": [_position("1", "Senior Product Manager")]})])

    import backend.scraper.ats.eightfold as eightfold
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)

    await eightfold.scrape("https://paypal.eightfold.ai/careers?country=Colombia&query=analyst")

    params = client.get.call_args_list[0].kwargs["params"]
    assert params["location"] == "Colombia"
    assert params["q"] == "analyst"


@pytest.mark.asyncio
async def test_scrape_builds_canonical_url_when_api_omits_it(monkeypatch):
    position = _position("42", "Senior Product Manager")
    position.pop("canonicalPositionUrl")
    client = _client([_response({"positions": [position]})])

    import backend.scraper.ats.eightfold as eightfold
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)

    jobs = await eightfold.scrape("https://paypal.eightfold.ai/careers")

    assert jobs[0]["url"] == "https://paypal.eightfold.ai/careers/job/42?domain=paypal.com"


@pytest.mark.asyncio
async def test_scrape_debug_reports_validation_rejections(monkeypatch):
    payload = {"positions": [_position("1", "Senior Product Manager"), _position("2", "PM")]}
    client = _client([_response(payload)])

    import backend.scraper.ats.eightfold as eightfold
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)

    jobs, rejected = await eightfold.scrape("https://paypal.eightfold.ai/careers", debug=True)

    assert [j["title"] for j in jobs] == ["Senior Product Manager"]
    assert rejected[0]["title"] == "PM"
    assert rejected[0]["selector"] == "eightfold_api"


@pytest.mark.asyncio
async def test_scrape_debug_reports_http_error(monkeypatch):
    client = _client([_response({}, status=500)])

    import backend.scraper.ats.eightfold as eightfold
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)

    jobs, rejected = await eightfold.scrape("https://paypal.eightfold.ai/careers", debug=True)

    assert jobs == []
    assert rejected[0]["reason"] == "HTTP 500"


@pytest.mark.asyncio
async def test_scrape_raises_when_board_is_gone(monkeypatch):
    from backend.scraper._shared.errors import BoardNotFoundError

    client = _client([_response({}, status=404)])

    import backend.scraper.ats.eightfold as eightfold
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)

    with pytest.raises(BoardNotFoundError):
        await eightfold.scrape("https://paypal.eightfold.ai/careers")


def test_mercadolibre_links_share_one_posting_key():
    assert posting_key("https://careers-meli.mercadolibre.com/es/job/12345") == (
        "eightfold:mercadolibre:12345")
    assert posting_key("https://mercadolibre.eightfold.ai/careers?pid=12345") == (
        "eightfold:mercadolibre:12345")
