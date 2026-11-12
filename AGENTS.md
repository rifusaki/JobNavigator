# `AGENTS.md` — Agent Guidelines for `JobNavigator` Fork

## 1. Mission & Scope

This repository is a fork of **`JobNavigator`** (`vesaias/JobNavigator`) extended with:
1. **Eightfold AI ATS handler** (`backend/scraper/ats/eightfold.py`) supporting `*.eightfold.ai` and custom-domain wrappers such as Mercado Libre (`https://careers-meli.mercadolibre.com/es`).
2. **LatAm Job Boards search mode** (`backend/scraper/sources/latam.py`) supporting **Get on Board**, **Computrabajo**, and **ElEmpleo** via `backend/scraper/_shared/job_boards.py`.
3. **Search Dorks search mode** (`backend/scraper/sources/dorks.py`) supporting Serper / Brave Search API dorking for LinkedIn hiring posts (`site:linkedin.com/posts`) and niche listings.
4. **Scraper Resiliency & Priority Scheduling:**
   * Browser hardening in `backend/scraper/_shared/browser.py` (`--disable-dev-shm-usage`, 2GB shm size in `docker-compose.yml`).
   * Defensive Playwright tab recycling (`_recycle_page` every 15 items), 25s atomic timeouts, rate-limit circuit breakers (HTTP 429), and fail-safe `finally:` page closing in `backend/scraper/sources/linkedin_personal.py`.
   * Fast-first orchestrator queue in `backend/scraper/orchestrator.py` prioritizing fast HTTP/API sources (`dorks`, `latam`, `eightfold`, `keyword`) to complete in minutes before heavy Chromium browser runs.
5. **Modular Resume Structure (Stack, Capacidades, Certificaciones, Idiomas):**
   * First-class separation between `stack` (tools, technologies, frameworks, cloud, languages) and `skills` (functional capabilities, analytical methodologies, domains).
   * Dedicated first-class sections for `certifications` (name, issuer, date, url) and `languages` (language, proficiency).
   * Full end-to-end support across:
     - Extraction & LLM PDF Parser (`backend/api/routes_resumes.py` - `parse_resume_pdf`).
     - Persona storage & import (`backend/api/routes_persona.py`).
     - AI Scorer flattener (`backend/analyzer/cv_scorer.py`).
     - Tailoring diffing (`frontend/src/screens/ResumeEditor.jsx` - `stk:${cat}`).
     - Shared section editors (`frontend/src/screens/ResumeSections.jsx` - `SkillsEditor`, `CertificationsEditor`, `LanguagesEditor`).
     - Template rendering with Jinja2 list formatting across all 10 templates (`backend/resume_templates/`).

* **Development host:** macOS (`/Users/rifusaki/localRepos/personal/JobNavigator`).
* **Execution host:** Windows home server accessible via `ssh 360` running Docker Compose.

---

## 2. Mandatory Codebase Rules (Read `CONTRIBUTING.md` First)

Before editing any file, read `CONTRIBUTING.md`. The upstream test suite enforces strict invariants that WILL fail if violated:

1. **Multi-Tenancy & Account Isolation (`MT_STRICT=1`):**
   * Every backend test runs with `MT_STRICT=1`. Any ORM query without an account context raises an error.
   * Never read `Setting` rows directly with `Setting.key == ...`. Always call `get_setting(db, key, default)` from `backend/accounts/settings.py`.
   * Any new setting key (such as `dork_search_provider` or `dork_search_api_key`) MUST be added to both `DEFAULT_SETTINGS` in `backend/seed.py` and `_SECTIONS` in `backend/accounts/settings.py`.
   * Never use raw `Session.get(Model, id)` on owned models; use `get_owned_or_404(db, Model, id)` from `backend/accounts/owned.py`.
   * `backend/tests/test_mt_leaks.py` tests every route against cross-account ID leaks.
2. **Search Mode Parity (`backend/tests/test_search_modes.py`):**
   * `backend/scraper/search_modes.py` (`SEARCH_MODES`) and `frontend/src/searchModes.js` (`SEARCH_MODES`) MUST match in keys, order, labels, `extension`, `needsQuery`, `needsTerm`, and default `sources`.
   * Notice that `frontend/src/searchModes.js` is parsed by a regex in `test_search_modes.py`: keep **one mode per line using plain literals** in `frontend/src/searchModes.js`.
3. **Resume Section Invariants (`backend/api/routes_resumes.py` & `frontend/src/screens/ResumeSections.jsx`):**
   * Section defaults: `_EMPTY_RESUME` in `routes_resumes.py` and `_CONTENT_DEFAULTS` in `routes_persona.py` MUST contain all active sections: `"summary"`, `"experience"`, `"stack"`, `"skills"`, `"education"`, `"certifications"`, `"languages"`, `"projects"`, `"publications"`.
   * Frontend ordering: `SECTION_ORDER` in `ResumeSections.jsx` MUST be:
     `['Header', 'Summary', 'Experience', 'Stack', 'Skills', 'Education', 'Certifications', 'Languages', 'Projects', 'Publications']`.
   * `sectionCounts(data)` MUST count all list and dictionary sections (`Stack`, `Skills`, `Certifications`, `Languages`, etc.).
   * Template values: Never render raw Python objects/lists. Use `_format_skill_value` in `_render_html` and `{{ (items_val | join(', ')) if (items_val is iterable and items_val is not string) else items_val }}` in Jinja2 templates.
4. **Frontend Design System & Stylelint Gate (`tests/tools/stylelint.py`):**
   * Build UI elements exclusively from primitives in `frontend/src/ui.jsx` and CSS custom property tokens in `frontend/src/theme.css` (see `frontend/src/DESIGN-SYSTEM.md`).
   * NEVER put raw hex colors, font families, border-radius values, or box-shadows in JSX or CSS files outside `ui.jsx` and `theme.css`.
   * Run `python3 tests/tools/stylelint.py` after any frontend edit—it must report `0` violations.
5. **Posting Keys & Reader Version (`backend/scraper/_shared/postings.py`):**
   * When adding URL patterns to `backend/scraper/_shared/postings.py` (for Eightfold, Get on Board, Computrabajo, ElEmpleo), increment `READER_VERSION` and add corresponding cases in `backend/tests/test_postings.py`.
6. **Zero Hardcoded Search Terms or User Rules:**
   * Do not hardcode user-specific keywords, cities, or exclusion rules in scraper modules. Read `search.search_term`, `search.location`, `search.country`, `search.hours_old`, and account settings dynamically through the helpers in `backend/scraper/_shared/job_boards.py` and `backend/scraper/_shared/filters.py`.

---

## 3. Verification & Test Commands

Run all three checks before considering a milestone complete:

```bash
# 1. Stylelint check (can run directly on host with python3)
python3 tests/tools/stylelint.py

# 2. Backend pytest suite (inside Docker backend container or local venv with MT_STRICT=1)
uv run pytest backend/tests -q -p no:cacheprovider -m 'not live'

# 3. Frontend Vitest unit tests (runs via node:24-alpine container or local frontend directory)
cd frontend && npm test -- --run
```

When deploying or testing on the Windows home server via `ssh 360`:
* Ensure `.env` has `JN_TELEMETRY=off`.
* After modifying backend `.py` files: `docker compose restart backend`.
* After modifying `frontend/` files (bypass credential helper via `DOCKER_CONFIG`):
  `DOCKER_CONFIG=/tmp/empty_docker docker compose up -d --build --no-deps frontend`.
