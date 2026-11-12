"""Every resume template prints skills cleanly: list values, stringified lists, and strings format without brackets or Python repr quotes."""
from pathlib import Path
import pytest

jinja2 = pytest.importorskip("jinja2")

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "resume_templates"


def _template_names():
    return sorted(p.name for p in TEMPLATES_DIR.iterdir()
                  if (p / "template.html.j2").exists())


def _render_direct(name, skills):
    from jinja2 import Environment, FileSystemLoader
    from markupsafe import Markup
    import re
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR / name)))
    env.filters["bold"] = lambda text: Markup(re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text or ""))
    return env.get_template("template.html.j2").render(
        header={"name": "Test User", "contact_items": []},
        summary="", experience=[], skills=skills,
        education=[], projects=[], publications=[],
        page_format="letter", fonts_base="", fonts={},
    )


@pytest.mark.parametrize("name", _template_names())
def test_template_renders_list_skills_without_brackets_direct(name):
    skills = {"Lenguajes": ["Python", "SQL", "R"]}
    html = _render_direct(name, skills)
    assert "Python, SQL, R" in html
    assert "['Python'" not in html
    assert "['" not in html


@pytest.mark.parametrize("name", _template_names())
def test_template_renders_list_of_dict_skills_without_brackets_direct(name):
    skills = [{"category": "Lenguajes", "items": ["Python", "SQL", "R"]}]
    html = _render_direct(name, skills)
    assert "Python, SQL, R" in html
    assert "['Python'" not in html


def test_render_html_formats_list_and_stringified_skills():
    from backend.api.routes_resumes import _render_html
    json_data = {
        "header": {"name": "Test User"},
        "skills": {
            "Lenguajes": ["Python", "SQL", "R"],
            "Datos": "['pandas', 'numpy']",
            "Cloud": "Azure, GCP",
        }
    }
    html = _render_html(json_data, "rifusaki_es", "letter")
    assert "Python, SQL, R" in html
    assert "pandas, numpy" in html
    assert "Azure, GCP" in html
    assert "['" not in html
