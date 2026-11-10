"""Eightfold AI ATS handler: GET /api/apply/v2/jobs on the tenant's Eightfold host.

Matched on `*.eightfold.ai` and on the custom-domain wrappers in
`_CUSTOM_EIGHTFOLD_HOSTS` (Mercado Libre serves its jobs from
`careers-meli.mercadolibre.com`, which is the `mercadolibre` tenant). Filters in the
original query string (`location` / `country`, `q` / `query`, `department`) are
forwarded to the JSON API. The API returns the whole board, twenty positions at a
time, so this handler paginates and emits one dict per posting.
"""
import logging
from urllib.parse import parse_qs, quote, urljoin, urlparse

import httpx

from backend.analyzer.work_arrangement import HYBRID, ONSITE, REMOTE
from backend.scraper._shared.errors import raise_if_board_gone
from backend.scraper._shared.filters import _validate_job

logger = logging.getLogger("jobnavigator.scraper.ats.eightfold")

_PAGE = 20
_MAX_PAGES = 50
_ARRANGEMENTS = {REMOTE, HYBRID, ONSITE}

# White-labelled Eightfold sites: custom host -> (Eightfold tenant host, API domain).
_CUSTOM_EIGHTFOLD_HOSTS = {
    "careers-meli.mercadolibre.com": ("mercadolibre.eightfold.ai", "mercadolibre.com"),
    "careers.mercadolibre.com": ("mercadolibre.eightfold.ai", "mercadolibre.com"),
    "explore.jobs.netflix.net": ("netflix.eightfold.ai", "netflix.com"),
}


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_eightfold(url: str) -> bool:
    """True for `*.eightfold.ai` boards and the known custom-domain wrappers."""
    host = _host(url)
    # The bare host is a company site, not a tenant board: it has no jobs API.
    return host.endswith(".eightfold.ai") or host in _CUSTOM_EIGHTFOLD_HOSTS


def target(url: str) -> tuple[str, str] | None:
    """Return `(eightfold_host, domain)` for an Eightfold board URL, or None.

    The host is where the API lives; the domain is the tenant the API keys postings
    by. For a direct `*.eightfold.ai` URL the tenant label is the domain stem unless
    the URL already carries `?domain=`.
    """
    parsed = urlparse(url)
    host = _host(url)
    if host in _CUSTOM_EIGHTFOLD_HOSTS:
        return _CUSTOM_EIGHTFOLD_HOSTS[host]
    if host.endswith(".eightfold.ai"):
        tenant = host.split(".")[0]
        domain = _first(parse_qs(parsed.query), "domain") or f"{tenant}.com"
        return host, domain
    return None


def posting_id(url: str) -> str | None:
    """Read the Eightfold position id from `?pid=`, `?jobId=`, or `/job/<id>`."""
    parsed = urlparse(url)
    for key in ("pid", "jobid"):
        value = _first(parse_qs(parsed.query), key)
        if value and value.isdigit():
            return value
    segments = [s for s in (parsed.path or "").split("/") if s]
    if "job" in segments:
        i = segments.index("job")
        if i + 1 < len(segments) and segments[i + 1].isdigit():
            return segments[i + 1]
    return None


def _first(qs: dict, key: str) -> str | None:
    vals = qs.get(key) or []
    return vals[0].strip() if vals and vals[0].strip() else None


def _filters(url: str) -> dict:
    """Map the board URL's query string onto the API's filter names."""
    qs = {k.lower(): v for k, v in parse_qs(urlparse(url).query).items()}
    filters = {}
    location = _first(qs, "location") or _first(qs, "country")
    if location:
        filters["location"] = location
    query = _first(qs, "q") or _first(qs, "query")
    if query:
        filters["q"] = query
    department = _first(qs, "department")
    if department:
        filters["department"] = department
    return filters


def _position_url(position: dict, host: str, domain: str) -> str:
    canonical = (position.get("canonicalPositionUrl") or "").strip()
    if canonical:
        return urljoin(f"https://{host}/", canonical)
    pid = str(position.get("id") or "").strip()
    if not pid:
        return ""
    return f"https://{host}/careers/job/{pid}?domain={quote(domain, safe='')}"


def _arrangement(position: dict) -> str | None:
    value = (position.get("work_location_option") or position.get("workplaceType") or "").strip().lower()
    return value if value in _ARRANGEMENTS else None


async def scrape(url: str, debug: bool = False) -> list[dict] | tuple:
    """Fetch every position on an Eightfold board, forwarding its filter query string."""
    resolved = target(url)
    if resolved is None:
        reason = "Not an Eightfold board"
        if debug:
            return [], [{"title": "(none)", "url": url, "selector": "eightfold_api", "reason": reason}]
        return []
    host, domain = resolved

    params = {"domain": domain, "num": str(_PAGE), **_filters(url)}
    jobs = []
    rejected = []
    seen = set()

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for page in range(_MAX_PAGES):
            page_params = {**params, "start": str(page * _PAGE)}
            resp = await client.get(f"https://{host}/api/apply/v2/jobs", params=page_params)
            if resp.status_code != 200:
                logger.warning(f"Eightfold API returned {resp.status_code} for {host}")
                if not debug:
                    raise_if_board_gone(resp.status_code, "Eightfold", host)
                    return jobs
                rejected.append({"title": "(none)", "url": str(resp.url), "selector": "eightfold_api",
                                 "reason": f"HTTP {resp.status_code}"})
                return jobs, rejected

            positions = (resp.json() or {}).get("positions") or []
            if not positions:
                break
            for position in positions:
                pid = str(position.get("id") or "").strip()
                title = (position.get("name") or "").strip()
                job_url = _position_url(position, host, domain)
                reason = _validate_job(title, job_url)
                if reason is not None:
                    if debug:
                        rejected.append({"title": title, "url": job_url, "selector": "eightfold_api",
                                         "reason": reason})
                    continue
                if pid and pid in seen:
                    continue
                if pid:
                    seen.add(pid)
                places = [p for p in (position.get("locations") or []) if p]
                jobs.append({
                    "title": title,
                    "url": job_url,
                    "location": position.get("location") or None,
                    "locations": places,
                    "arrangement": _arrangement(position),
                })
            if len(positions) < _PAGE:
                break

    logger.info(f"Eightfold API: fetched {len(jobs)} jobs for {host}")
    if debug:
        return jobs, rejected
    return jobs
