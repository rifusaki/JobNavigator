"""Search Dorks source: run web-search dorks and ingest the results as jobs.

`search.search_term` holds one dork per line (for example
`site:linkedin.com/posts "pasantía" Colombia`). The account's provider
(`dork_search_provider`: `serper` or `brave`) and key (`dork_search_api_key`) come from
Settings and are read through `get_setting`, so every account bills its own key.
Results are rows for the job_boards.py pipeline: the snippet is the first description,
and up to twenty-five result pages are read for the full text.
"""
from urllib.parse import urlparse

import httpx

from backend.models.db import Search
from backend.scraper._shared import job_boards
from backend.scraper._shared.html_text import html_to_text
from backend.scraper._shared.job_boards import Board, BoardError, make_row

_SERPER = "https://google.serper.dev/search"
_BRAVE = "https://api.search.brave.com/res/v1/web/search"
_MAX_DETAILS = 25
_MAX_PER_QUERY = 100
# Brave Web Search caps `count` at 20; Serper accepts up to 100.
_BRAVE_PER_QUERY = 20
_PUBLIC_SECOND_LEVEL = {"ac", "co", "com", "edu", "gov", "net", "org"}


def _time_filter(hours_old: int | None) -> str | None:
    """The provider window, or None when the search has no age limit."""
    if not hours_old:
        return None
    hours = hours_old
    if hours <= 24:
        return "d"
    if hours <= 168:
        return "w"
    if hours <= 720:
        return "m"
    return "y"


def _queries(search: Search) -> list:
    return [line.strip() for line in (search.search_term or "").splitlines() if line.strip()]


def _company(title: str, url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "LinkedIn Post"
    labels = [p for p in host.removeprefix("www.").split(".") if p]
    # `jobs.acme.co.uk` and `acme.com.br` name acme, not "co" or "com".
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _PUBLIC_SECOND_LEVEL:
        return labels[-3].replace("-", " ").replace("_", " ").title()
    if len(labels) >= 2:
        return labels[-2].replace("-", " ").replace("_", " ").title()
    return ""


def _snippet(item: dict) -> str:
    return " ".join((item.get("snippet") or item.get("description") or "").split())


def _row(item: dict) -> dict:
    url = (item.get("link") or item.get("url") or "").strip()
    title = " ".join((item.get("title") or "").split())
    return make_row(
        title=title, company=_company(title, url), url=url,
        description=_snippet(item), posted=item.get("date") or item.get("age") or None)


def _parse(provider: str, body: dict) -> list:
    if provider == "brave":
        return ((body.get("web") or {}).get("results") or [])
    return body.get("organic") or []


async def _search(client: httpx.AsyncClient, provider: str, key: str, query: str, count: int,
                  hours_old: int | None) -> list:
    window = _time_filter(hours_old)
    if provider == "brave":
        params = {"q": query, "count": min(count, _BRAVE_PER_QUERY),
                  "text_decorations": "false", "safesearch": "off"}
        if window:
            params["freshness"] = "p" + window
        resp = await client.get(_BRAVE, params=params,
                                headers={"Accept": "application/json", "X-Subscription-Token": key})
    else:
        body = {"q": query, "num": min(count, _MAX_PER_QUERY)}
        if window:
            body["tbs"] = f"qdr:{window}"
        resp = await client.post(_SERPER, json=body,
                                 headers={"X-API-KEY": key, "Content-Type": "application/json"})
    if resp.status_code >= 400:
        raise BoardError(f"HTTP {resp.status_code} from the {provider.title()} search API")
    return _parse(provider, resp.json() or {})


def _lister(provider: str, key: str):
    async def _list(client: httpx.AsyncClient, search: Search, limit: int) -> list:
        if not key:
            raise BoardError(f"Search Dorks needs a {provider.title()} API key (Settings › Search Dorks)")
        rows = []
        seen = set()
        for query in _queries(search):
            for item in await _search(client, provider, key, query, limit, search.hours_old):
                row = _row(item)
                if not row["title"] or not row["url"].startswith(("http://", "https://")):
                    continue
                if row["url"] in seen:
                    continue
                seen.add(row["url"])
                rows.append(row)
                if len(rows) >= limit:
                    break
            if len(rows) >= limit:
                break
        return rows[:limit]
    return _list


async def _detail(client: httpx.AsyncClient, row: dict) -> None:
    """Read the public page and keep the longer of its text and the search snippet."""
    resp = await client.get(row["url"])
    if resp.status_code >= 400:
        return
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        tag.decompose()
    text = html_to_text(str(soup.body or soup))
    if len(text) > len(row.get("description") or "") and len(text) >= 50:
        row["description"] = text[:30_000]


def _config(db) -> tuple[str, str]:
    from backend.accounts.settings import get_setting
    provider = (get_setting(db, "dork_search_provider", "serper") or "serper").strip().lower()
    key = (get_setting(db, "dork_search_api_key", "") or "").strip()
    if provider not in ("serper", "brave"):
        raise BoardError(f"Unknown dork search provider {provider!r} (use serper or brave)")
    return provider, key


def _boards(provider: str, key: str) -> dict:
    return {"dorks": Board("Search Dorks", _lister(provider, key), _detail, max_details=_MAX_DETAILS)}


async def run(search: Search) -> dict:
    from backend.models.db import SessionLocal
    db = SessionLocal()
    try:
        provider, key = _config(db)
    finally:
        db.close()
    return await job_boards.run(search, _boards(provider, key))


def _failed_preview(search: Search, message: str) -> dict:
    """The standard preview payload, with the setting that blocks the test named."""
    return {
        "search_name": search.name, "error": message, "duration": 0.0,
        "details_sampled": 0, "detail_limit": job_boards.PREVIEW_DETAIL_LIMIT,
        "preview_note": message, "raw_count": 0, "after_filter": 0,
        "source_breakdown": {}, "source_errors": {"dorks": message},
        "company_breakdown": {}, "include_keywords": [], "exclude_keywords": [],
        "company_filter": search.company_filter or [], "company_exclude": [],
        "jobs": [],
        "config": {"mode": "dorks", "search_term": search.search_term or "",
                   "sources": ["dorks"], "results_wanted": job_boards.PREVIEW_LIMIT},
    }


async def preview(search: Search, db) -> dict:
    try:
        provider, key = _config(db)
    except BoardError as e:
        return _failed_preview(search, str(e))
    if not key:
        return _failed_preview(
            search, f"Search Dorks needs a {provider.title()} API key (Settings › Search Dorks)")
    return await job_boards.preview(search, db, _boards(provider, key))
