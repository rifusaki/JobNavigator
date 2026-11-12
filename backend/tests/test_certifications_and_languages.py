"""Tests for first-class Certifications and Languages support across
schema defaults, Persona content, CV scoring flattener, and template rendering.
"""
from backend.analyzer.cv_scorer import _flatten_resume
from backend.api.routes_persona import _CONTENT_DEFAULTS, _resume_content_from
from backend.api.routes_resumes import _EMPTY_RESUME, _render_html


def test_empty_resume_and_content_defaults_include_new_sections():
    assert "stack" in _EMPTY_RESUME
    assert "certifications" in _EMPTY_RESUME
    assert "languages" in _EMPTY_RESUME
    assert _EMPTY_RESUME["stack"] == {}
    assert _EMPTY_RESUME["certifications"] == []
    assert _EMPTY_RESUME["languages"] == []

    defaults_dict = dict(_CONTENT_DEFAULTS)
    assert "stack" in defaults_dict
    assert "certifications" in defaults_dict
    assert "languages" in defaults_dict
    assert defaults_dict["stack"] == {}
    assert defaults_dict["certifications"] == []
    assert defaults_dict["languages"] == []


def test_resume_content_from_preserves_certifications_and_languages():
    raw = {
        "summary": "Data specialist",
        "experience": [],
        "stack": {"Lenguajes": "Python, SQL, R"},
        "skills": {"Ingeniería de datos": "ETL pipelines"},
        "education": [{"school": "UNAL", "degree": "Física"}],
        "certifications": [
            {
                "name": "Desarrolla+ Colombia – Java Backend",
                "issuer": "Ada | Mercado Libre",
                "date": "oct. 2026",
            }
        ],
        "languages": [
            {"language": "Español", "proficiency": "Nativo"},
            {"language": "Inglés", "proficiency": "Profesional"},
        ],
    }
    extracted = _resume_content_from(raw)
    assert extracted["stack"] == {"Lenguajes": "Python, SQL, R"}
    assert extracted["skills"] == {"Ingeniería de datos": "ETL pipelines"}
    assert len(extracted["certifications"]) == 1
    assert extracted["certifications"][0]["name"] == "Desarrolla+ Colombia – Java Backend"
    assert len(extracted["languages"]) == 2
    assert extracted["languages"][0]["language"] == "Español"


def test_flatten_resume_includes_certifications_and_languages():
    data = {
        "header": {"name": "Test User"},
        "stack": {
            "Lenguajes": ["Python", "SQL", "R"],
            "Cloud": "Azure, GCP",
        },
        "skills": {
            "Ingeniería de datos": "ETL pipelines, data modeling",
        },
        "certifications": [
            {
                "name": "Developing AI Applications with Python and Flask",
                "issuer": "IBM",
                "date": "may. 2024",
            }
        ],
        "languages": [
            {"language": "Español", "proficiency": "Competencia bilingüe o nativa"},
            {"language": "Francés", "proficiency": "Competencia básica"},
        ],
    }
    text = _flatten_resume(data)
    assert "## Stack" in text
    assert "Lenguajes: Python, SQL, R" in text
    assert "Cloud: Azure, GCP" in text
    assert "## Capacidades" in text
    assert "Ingeniería de datos: ETL pipelines, data modeling" in text
    assert "## Certifications & Courses" in text
    assert "Developing AI Applications with Python and Flask (IBM — may. 2024)" in text
    assert "## Languages" in text
    assert "Español: Competencia bilingüe o nativa" in text
    assert "Francés: Competencia básica" in text


def test_render_templates_with_certifications_and_languages():
    data = {
        "header": {"name": "Rifusaki User", "contact_items": []},
        "summary": "Physics and Machine Learning specialist.",
        "experience": [],
        "stack": {"Lenguajes": ["Python", "SQL", "R"]},
        "skills": {"Ingeniería de datos": "ETL, data pipelines"},
        "education": [{"school": "Universidad Nacional de Colombia", "degree": "Física"}],
        "certifications": [
            {
                "name": "Introduction to Cloud Computing",
                "issuer": "IBM",
                "date": "abr. 2024",
            }
        ],
        "languages": [
            {"language": "Español", "proficiency": "Nativo"},
            {"language": "Inglés", "proficiency": "C1 Avanzado"},
        ],
    }

    # Test rifusaki (English)
    html_en = _render_html(data, "rifusaki", "letter")
    assert "Stack" in html_en
    assert "Python, SQL, R" in html_en
    assert "Capabilities" in html_en
    assert "Certifications & Courses" in html_en
    assert "Introduction to Cloud Computing" in html_en
    assert "IBM" in html_en
    assert "Languages" in html_en
    assert "Español" in html_en
    assert "C1 Avanzado" in html_en

    # Test rifusaki_es (Spanish)
    html_es = _render_html(data, "rifusaki_es", "letter")
    assert "Stack" in html_es
    assert "Capacidades" in html_es
    assert "Certificaciones & Cursos" in html_es
    assert "Introduction to Cloud Computing" in html_es
    assert "IBM" in html_es
    assert "Idiomas" in html_es
    assert "Español" in html_es
    assert "C1 Avanzado" in html_es

    # Test that empty certifications/languages do NOT render section titles
    data_empty = {
        "header": {"name": "Empty User"},
        "summary": "Summary text",
        "experience": [],
        "skills": {},
        "education": [],
        "certifications": [],
        "languages": [],
    }
    html_empty = _render_html(data_empty, "rifusaki", "letter")
    assert "Certifications & Courses" not in html_empty
    assert "Languages" not in html_empty
