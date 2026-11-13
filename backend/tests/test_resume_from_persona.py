import pytest
from backend.models.db import Persona, Resume
from backend.accounts.owned import get_persona


def test_resume_from_persona_empty_raises_400(api_client, test_db):
    """When Persona has no resume_content, POST /api/resumes/from-persona fails 400."""
    p = get_persona(test_db, create=True)
    p.resume_content = {}
    test_db.commit()

    resp = api_client.post("/api/resumes/from-persona", json={})
    assert resp.status_code == 400
    assert "resume_content" in resp.json()["detail"]


def test_resume_from_persona_success(api_client, test_db):
    """Creating a Base resume from a rich Persona carries all sections, stack, certifications, and languages."""
    p = get_persona(test_db, create=True)
    p.contact = {
        "first_name": "Martina",
        "last_name": "García Mejía",
        "email": "martina@rifusaki.com",
        "phone": "(+57) 316 577 8264",
        "city": "Bogota",
        "country": "Colombia",
        "linkedin": "https://www.linkedin.com/in/rifusaki/",
        "github": "https://github.com/rifusaki",
    }
    p.resume_content = {
        "header": {
            "name": "Martina García Mejía",
            "title": "Data Engineer • Physics",
            "contact_items": [{"text": "Portfolio", "url": "https://rifusaki.com"}],
        },
        "summary": "Experienced Data Engineer...",
        "experience": [{"company": "Intwo", "title": "Data Engineer", "bullets": ["Built pipelines"]}],
        "stack": {"Lenguajes": ["Python", "SQL"]},
        "skills": {"Ingeniería de datos": ["ETL"]},
        "education": [{"institution": "UNAL", "degree": "BS"}],
        "certifications": [{"name": "Azure Data", "issuer": "Microsoft"}],
        "languages": [{"language": "Español", "proficiency": "Nativo"}],
        "projects": [{"title": "catnip", "description": "CLI"}],
        "publications": [],
    }
    test_db.commit()

    resp = api_client.post("/api/resumes/from-persona", json={"name": "Martina Base"})
    assert resp.status_code == 201
    data = resp.json()

    assert data["name"] == "Martina Base"
    assert data["is_base"] is True
    jd = data["json_data"]
    assert jd["summary"] == "Experienced Data Engineer..."
    assert jd["header"]["name"] == "Martina García Mejía"
    assert jd["header"]["title"] == "Data Engineer • Physics"

    # Contact items should include location, email, phone, linkedin, github, and preserved portfolio
    texts = [c["text"] for c in jd["header"]["contact_items"]]
    assert "Bogota, Colombia" in texts
    assert "martina@rifusaki.com" in texts
    assert "(+57) 316 577 8264" in texts
    assert "LinkedIn" in texts
    assert "GitHub" in texts
    assert "Portfolio" in texts

    # Stack and skills
    assert jd["stack"]["Lenguajes"] == ["Python", "SQL"]
    assert jd["skills"]["Ingeniería de datos"] == ["ETL"]

    # Certifications & languages
    assert len(jd["certifications"]) == 1
    assert jd["certifications"][0]["name"] == "Azure Data"
    assert len(jd["languages"]) == 1
    assert jd["languages"][0]["language"] == "Español"


def test_resume_from_persona_overwrite_base(api_client, test_db):
    """Overwriting an existing base resume updates json_data and keeps the ID."""
    p = get_persona(test_db, create=True)
    p.contact = {"first_name": "Test", "last_name": "User"}
    p.resume_content = {"summary": "Old summary", "experience": []}
    test_db.commit()

    # Create base resume
    r = Resume(name="Existing Base", is_base=True, json_data={"summary": "Old"})
    test_db.add(r)
    test_db.commit()
    test_db.refresh(r)

    # Update persona
    p.resume_content = {"summary": "New summary from persona", "experience": []}
    test_db.commit()

    resp = api_client.post("/api/resumes/from-persona", json={
        "overwrite_resume_id": str(r.id),
        "name": "Updated Base",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == str(r.id)
    assert data["name"] == "Updated Base"
    assert data["json_data"]["summary"] == "New summary from persona"


def test_resume_from_persona_overwrite_tailored_fails(api_client, test_db):
    """Attempting to overwrite a tailored copy from Persona raises 400."""
    p = get_persona(test_db, create=True)
    p.resume_content = {"summary": "Summary", "experience": []}
    test_db.commit()

    tailored = Resume(name="Tailored Copy", is_base=False, json_data={})
    test_db.add(tailored)
    test_db.commit()
    test_db.refresh(tailored)

    resp = api_client.post("/api/resumes/from-persona", json={
        "overwrite_resume_id": str(tailored.id),
    })
    assert resp.status_code == 400
    assert "Cannot overwrite a tailored resume" in resp.json()["detail"]
