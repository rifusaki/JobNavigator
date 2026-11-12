import copy
from sqlalchemy.orm.attributes import flag_modified
from backend.models.db import SessionLocal, Persona, Resume

CERTS = [
    {
        "name": "Desarrolla+ Colombia – Java Backend",
        "issuer": "Ada | Mercado Libre",
        "date": "oct. 2026",
        "url": "",
    },
    {
        "name": "Developing AI Applications with Python and Flask",
        "issuer": "IBM",
        "date": "may. 2024",
        "url": "",
    },
    {
        "name": "Developing Back-End Apps with Node.js and Express",
        "issuer": "IBM",
        "date": "may. 2024",
        "url": "",
    },
    {
        "name": "Developing Front-End Apps with React",
        "issuer": "IBM",
        "date": "may. 2024",
        "url": "",
    },
    {
        "name": "GIS Data Acquisition and Map Design",
        "issuer": "University of Toronto",
        "date": "abr. 2024",
        "url": "",
    },
    {
        "name": "Introduction to Cloud Computing",
        "issuer": "IBM",
        "date": "abr. 2024",
        "url": "",
    },
    {
        "name": "Programa Especializado | Python for Everybody",
        "issuer": "University of Michigan",
        "date": "sept. 2021",
        "url": "",
    },
]

LANGS = [
    {
        "language": "Español",
        "proficiency": "Competencia bilingüe o nativa",
    },
    {
        "language": "Inglés",
        "proficiency": "Competencia profesional completa",
    },
    {
        "language": "Francés",
        "proficiency": "Competencia básica",
    },
]

STACK = {
    "Lenguajes": "Python, R, SQL, TypeScript/JavaScript, LaTeX, Go (básico)",
    "Datos y ML": "pandas, numpy, scipy, matplotlib, ggplot2, PyTorch, scikit-learn, Power BI, Grafana",
    "Cloud e infraestructura": "Azure Function Apps, Azure Data Factory, Microsoft SQL Server, Google Cloud Storage, Cloudflare",
    "Desarrollo": "Express.js, Node.js, React, Flask, Git, Conda, Pixi",
    "Geoespacial": "QGIS, Análisis espacial",
}

SKILLS = {
    "Ingeniería de datos": "Diseño e implementación de pipelines ETL, integración de fuentes, automatización de flujos",
    "Análisis y modelado": "Modelado estadístico, series de tiempo, modelos autorregresivos, visualización",
    "Machine learning": "Clasificación, extracción de características, visión por computadora, entrenamiento y evaluación de modelos",
    "Computación científica": "Métodos numéricos, simulación, modelado de sistemas físicos",
    "Comunicación técnica": "Redacción, traducción, documentación",
}


def run():
    db = SessionLocal()
    try:
        for p in db.query(Persona).all():
            rc = copy.deepcopy(p.resume_content or {})
            rc["certifications"] = copy.deepcopy(CERTS)
            rc["languages"] = copy.deepcopy(LANGS)
            rc["stack"] = copy.deepcopy(STACK)
            rc["skills"] = copy.deepcopy(SKILLS)
            p.resume_content = rc
            flag_modified(p, "resume_content")
            print(f"Updated Persona {p.id}")

        for r in db.query(Resume).all():
            jd = copy.deepcopy(r.json_data or {})
            jd["certifications"] = copy.deepcopy(CERTS)
            jd["languages"] = copy.deepcopy(LANGS)
            jd["stack"] = copy.deepcopy(STACK)
            jd["skills"] = copy.deepcopy(SKILLS)
            r.json_data = jd
            flag_modified(r, "json_data")
            print(f"Updated Resume {r.id}: {r.name}")

        db.commit()
        print("Migration committed successfully!")
    finally:
        db.close()


if __name__ == "__main__":
    run()
