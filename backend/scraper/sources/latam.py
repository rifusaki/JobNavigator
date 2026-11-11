"""LatAm boards source: Get on Board, Computrabajo and ElEmpleo through job_boards.py.

| board        | listing                                      | description            |
| ------------ | -------------------------------------------- | ---------------------- |
| getonbrd     | public v0 JSON search, 50 per page           | in the listing         |
| computrabajo | regional HTML search (`co`, `ar`, `mx`, …)   | job page, 40 per run   |
| elempleo     | Colombia HTML search                         | job page, 40 per run   |

A search picks boards in `sources`; each board's key is the stored Job.source. Country
picks Computrabajo's regional site (Colombia by default), filters Get on Board rows by
their listed countries, and keeps ElEmpleo on its Colombian site. Location narrows the
listing where the board accepts a city and is matched accent-insensitively for the boards
that filter locally.
"""
import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, quote_plus, urljoin

import httpx

from backend.analyzer.work_arrangement import HYBRID, ONSITE, REMOTE
from backend.countries import split_country_suffix, supported_countries
from backend.models.db import Search
from backend.scraper._shared import job_boards
from backend.scraper._shared.html_text import html_to_text
from backend.scraper._shared.job_boards import (Board, BoardError, annual_usd, city_of, country_name,
                                                iso_from_ts, make_row, term_of, too_old)

_GETONBRD = "https://www.getonbrd.com"
_GETONBRD_SEARCH = f"{_GETONBRD}/api/v0/search/jobs"
_GETONBRD_PAGE = 50
_MAX_PAGES = 5
_MAX_DETAILS = 40

_COMPUTRABAJO_CODES = {
    "colombia": "co", "argentina": "ar", "mexico": "mx", "chile": "cl", "peru": "pe",
}


def _slug(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")


def _iso(value):
    return value if isinstance(value, str) and value.strip() else None


# Computrabajo and ElEmpleo print Spanish relative dates ("Hace 2 días", "Ayer").
# job_boards.too_old() reads ISO dates, so turn the card's age into one.
_ES_AGE = re.compile(r"hace\s+(?:mas\s+de\s+)?(un|una|\d+)\s+(minuto|hora|dia|semana|mes|ano)(?:es|s)?", re.I)
_ES_UNITS = {"minuto": "minutes", "hora": "hours", "dia": "days",
             "semana": "weeks", "mes": "days", "ano": "days"}
_ES_MULTIPLIER = {"mes": 30, "ano": 365}


def _es_posted(text: str) -> str | None:
    folded = _slug(text).replace("-", " ")
    now = datetime.now(timezone.utc)
    if "hoy" in folded:
        return now.isoformat()
    if "ayer" in folded:
        return (now - timedelta(days=1)).isoformat()
    match = _ES_AGE.search(folded)
    if not match:
        return None
    amount = 1 if match.group(1) in ("un", "una") else int(match.group(1))
    unit = match.group(2)
    amount *= _ES_MULTIPLIER.get(unit, 1)
    return (now - timedelta(**{_ES_UNITS[unit]: amount})).isoformat()


def _search_country(search: Search) -> str:
    """The search's Country, falling back to a country written at the end of Location."""
    name = country_name(search)
    if name:
        return name
    _, code = split_country_suffix(getattr(search, "location", "") or "")
    return dict(supported_countries()).get(code or "", "")


def _computrabajo_code(search: Search) -> str:
    return _COMPUTRABAJO_CODES.get(_search_country(search).lower(), "co")


def _arrangement(text: str):
    folded = _slug(text)
    if not folded:
        return None
    if "hibrid" in folded or "hybrid" in folded or ("remot" in folded and "presencial" in folded):
        return HYBRID
    if "remot" in folded or "teletrabajo" in folded or "home-office" in folded:
        return REMOTE
    if "presencial" in folded:
        return ONSITE
    return None


def _place_name(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    return str(value.get("name") or (value.get("attributes") or {}).get("name") or "").strip()


def _countries(attrs: dict) -> list:
    raw = attrs.get("countries") or []
    if isinstance(raw, str):
        raw = [raw]
    return [name for name in (_place_name(value) for value in raw) if name]


# ── Get on Board ────────────────────────────────────────────────────────────

def _company_name(raw, included: dict) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if not isinstance(raw, dict):
        return ""
    for node in (raw, raw.get("data")):
        if not isinstance(node, dict):
            continue
        name = (node.get("attributes") or {}).get("name") or node.get("name")
        if name:
            return str(name).strip()
        related = included.get(node.get("id") or "") or {}
        name = (related.get("attributes") or {}).get("name")
        if name:
            return str(name).strip()
    return ""


def _company(job: dict, included: dict) -> str:
    attrs = job.get("attributes") or {}
    relationship = ((job.get("relationships") or {}).get("company") or {}).get("data")
    for candidate in (attrs.get("company"), relationship):
        name = _company_name(candidate, included)
        if name:
            return name
    return ""


def _getonbrd_check(row: dict, search: Search):
    """Get on Board has no country query parameter, so drop rows it says are elsewhere."""
    wanted = _search_country(search)
    countries = [str(c) for c in row.get("countries") or [] if c]
    if not wanted or not countries:
        return None
    if any(_slug(c) in ("worldwide", "anywhere", "global", "remote") for c in countries):
        return None
    if any(_slug(wanted) == _slug(c) for c in countries):
        return None
    return f"Not open to {wanted}"


def _getonbrd_row(job: dict, included: dict) -> dict:
    attrs = job.get("attributes") or {}
    remote = attrs.get("remote") is True
    modality = (attrs.get("remote_modality") or attrs.get("modality") or "").strip()
    countries = _countries(attrs)
    country_text = ", ".join(countries)
    raw_location = attrs.get("location") or attrs.get("locations") or ""
    if isinstance(raw_location, list):
        city = ", ".join(p for p in (_place_name(value) for value in raw_location) if p)
    else:
        city = _place_name(raw_location) if isinstance(raw_location, dict) else str(raw_location or "").strip()
    if city and country_text and _slug(country_text) not in _slug(city):
        location = f"{city}, {country_text}"
    else:
        location = city or country_text
    location = location or ("Remote" + (f" ({modality})" if modality and modality.lower() != "remote" else "")
                            if remote else "")
    description = "\n\n".join(
        html_to_text(attrs.get(field) or "") for field in ("description", "functions", "benefits")
        if (attrs.get(field) or "").strip())
    sal_min, sal_max = annual_usd(
        attrs.get("min_salary"), attrs.get("max_salary"),
        attrs.get("salary_period") or "ANNUAL",
        attrs.get("salary_currency") or attrs.get("currency") or "USD")
    link = (job.get("links") or {}).get("public_url") or ""
    return make_row(
        title=attrs.get("title"), company=_company(job, included),
        url=urljoin(_GETONBRD + "/", link) if link else f"{_GETONBRD}/jobs/{job.get('id') or ''}",
        location=location.strip(), description=description,
        salary_min=sal_min, salary_max=sal_max,
        arrangement=_arrangement(modality) or (REMOTE if remote else None),
        posted=iso_from_ts(attrs.get("published_at")) or _iso(attrs.get("published_at")),
        countries=countries,
        ref=str(job.get("id") or "") or None)


async def _list_getonbrd(client: httpx.AsyncClient, search: Search, limit: int) -> list:
    rows = []
    for page in range(1, _MAX_PAGES + 1):
        resp = await client.get(_GETONBRD_SEARCH, params={
            "query": term_of(search), "per_page": _GETONBRD_PAGE, "page": page,
            "expand": '["company"]'})
        if resp.status_code >= 400:
            raise BoardError(f"HTTP {resp.status_code} from the Get on Board API")
        body = resp.json() or {}
        jobs = body.get("data") or []
        included = {i.get("id"): i for i in body.get("included") or [] if isinstance(i, dict)}
        batch = [_getonbrd_row(j, included) for j in jobs if isinstance(j, dict)]
        fresh = [r for r in batch if not too_old(r, search.hours_old)]
        rows += fresh
        if len(jobs) < _GETONBRD_PAGE or len(fresh) < len(batch) or len(rows) >= limit:
            break
    return rows[:limit]


# ── Computrabajo ────────────────────────────────────────────────────────────

def _card_text(card, *selectors) -> str:
    for selector in selectors:
        el = card.select_one(selector)
        if el and el.get_text(strip=True):
            return " ".join(el.get_text(" ", strip=True).split())
    return ""


def _card_link(card, base: str) -> str:
    for selector in ("a.js-offer-title[href]", "h2 a.js-o-link[href]", "h2 a[href]",
                     "a[href*='/ofertas-trabajo/']", "a[href*='/ofertas-de-trabajo/']", "a[href]"):
        el = card.select_one(selector)
        if el and el.get("href"):
            return urljoin(base + "/", el["href"])
    return ""


def _computrabajo_row(card, base: str) -> dict:
    title = _card_text(card, "h2 a.js-o-link", "h2 a", "h2")
    company = _card_text(card, "a[offer-grid-article-company-url]", "p.dFlex a", "p.dFlex")
    location = _card_text(card, "p.fs16:not(.dFlex) span", "p.fs16:not(.dFlex)",
                          "[class*=ubicacion]", ".location")
    posted = _card_text(card, "p.fs13.fc_aux", "time", "[class*=fecha]")
    return make_row(
        title=title, company=company, url=_card_link(card, base), location=location,
        description=_card_text(card, ".description", ".resumen"),
        arrangement=_arrangement(_card_text(card, "div.fs13")),
        posted=_es_posted(posted) or posted or None)


async def _list_computrabajo(client: httpx.AsyncClient, search: Search, limit: int) -> list:
    code = _computrabajo_code(search)
    base = f"https://{code}.computrabajo.com"
    path = f"{base}/trabajo-de-{quote(_slug(term_of(search)) or 'empleo')}"
    params = {"p": 1}
    city = city_of(search)
    if city:
        params["l"] = city
    rows = []
    seen = set()
    for page in range(1, _MAX_PAGES + 1):
        resp = await client.get(path, params=dict(params, p=page))
        if resp.status_code == 404 and page > 1:
            break
        if resp.status_code >= 400:
            raise BoardError(f"HTTP {resp.status_code} from Computrabajo")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("article.box_offer, div.box_offer, article[data-id]")
        batch = [_computrabajo_row(card, base) for card in cards]
        batch = [r for r in batch if r.get("title") and r.get("url") and r["url"] not in seen]
        seen.update(r["url"] for r in batch)
        fresh = [r for r in batch if not too_old(r, search.hours_old)]
        rows += fresh
        if not cards or not batch or len(rows) >= limit:
            break
    return rows[:limit]


async def _detail_computrabajo(client: httpx.AsyncClient, row: dict) -> None:
    resp = await client.get(row["url"])
    if resp.status_code >= 400:
        raise BoardError(f"HTTP {resp.status_code} from {row['url']}")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    section = soup.select_one('div[div-link="oferta"]')
    if section:
        text = html_to_text(str(section))
    else:
        texts = [html_to_text(str(el)) for el in soup.select(
            "div.box_detail, div[class*=descripcion], section[class*=descripcion], #descripcion")]
        text = max(texts, key=len, default="")
    if len(text) >= 50:
        row["description"] = text


# ── ElEmpleo ────────────────────────────────────────────────────────────────

_ELEMPLEO = "https://www.elempleo.com"


def _elempleo_data(card) -> dict:
    holder = card.select_one("[data-ga4-offerdata]")
    if not holder:
        return {}
    try:
        value = json.loads(holder.get("data-ga4-offerdata") or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _elempleo_row(card, base: str) -> dict:
    data = _elempleo_data(card)
    title = _card_text(card, "a.js-offer-title", "h2 a", "h2") or str(data.get("title") or "")
    company = (_card_text(card, ".js-offer-company", ".empresa", "[class*=empresa]", ".company")
               or str(data.get("company") or ""))
    location = (_card_text(card, ".js-offer-city", ".ciudad", "[class*=ciudad]", ".location")
                or str(data.get("location") or ""))
    posted = _card_text(card, ".js-offer-date", "time", ".fecha", "[class*=fecha]")
    return make_row(
        title=title, company=company, url=_card_link(card, base), location=location,
        description=_card_text(card, ".description", ".resumen"),
        arrangement=_arrangement(_card_text(card, ".js-work-modality")),
        posted=_es_posted(posted) or posted or None)


async def _list_elempleo(client: httpx.AsyncClient, search: Search, limit: int) -> list:
    term = quote_plus(term_of(search) or "empleo")
    path = f"{_ELEMPLEO}/co/ofertas-empleo/trabajo-{term}"
    params = {"pagina": 0}
    city = city_of(search)
    if city:
        params["ciudad"] = city
    rows = []
    seen = set()
    for page in range(1, _MAX_PAGES + 1):
        resp = await client.get(path, params=dict(params, pagina=page - 1))
        # ElEmpleo answers 404 when the query has no matches, including page 1.
        if resp.status_code == 404:
            break
        if resp.status_code >= 400:
            raise BoardError(f"HTTP {resp.status_code} from ElEmpleo")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("div.result-item, article.result-item, li.result-item")
        batch = [_elempleo_row(card, _ELEMPLEO) for card in cards]
        batch = [r for r in batch if r.get("title") and r.get("url") and r["url"] not in seen]
        seen.update(r["url"] for r in batch)
        fresh = [r for r in batch if not too_old(r, search.hours_old)]
        rows += fresh
        if not cards or not batch or len(rows) >= limit:
            break
    return rows[:limit]


async def _detail_elempleo(client: httpx.AsyncClient, row: dict) -> None:
    resp = await client.get(row["url"])
    if resp.status_code >= 400:
        raise BoardError(f"HTTP {resp.status_code} from {row['url']}")
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    section = soup.select_one("div.description-block") or soup.select_one("div[class*=description]")
    if section:
        text = html_to_text(str(section))
    else:
        texts = [html_to_text(str(el)) for el in soup.select(
            "div.descripcion-oferta, div[class*=descripcion], #descripcion, section[class*=descripcion]")]
        text = max(texts, key=len, default="")
    if len(text) >= 50:
        row["description"] = text


BOARDS = {
    "getonbrd": Board("Get on Board", _list_getonbrd, check=_getonbrd_check),
    "computrabajo": Board("Computrabajo", _list_computrabajo, _detail_computrabajo,
                          max_details=_MAX_DETAILS, local_city=True),
    "elempleo": Board("ElEmpleo", _list_elempleo, _detail_elempleo,
                      max_details=_MAX_DETAILS, local_city=True),
}


def _picked(search: Search) -> dict:
    return {s: BOARDS[s] for s in (search.sources or []) if s in BOARDS}


async def run(search: Search) -> dict:
    return await job_boards.run(search, _picked(search))


async def preview(search: Search, db) -> dict:
    return await job_boards.preview(search, db, _picked(search))
