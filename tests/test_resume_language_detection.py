import pytest
from app import app
from utils.resume_language_detector import ResumeLanguageDetector, resume_language_detector


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_detect_english_resume():
    detector = ResumeLanguageDetector()
    resume_sample = """
    Software Engineer Resume
    Summary: Dedicated computer science graduate with experience developing full-stack web applications.
    Education: Bachelor of Technology in Computer Science, State University.
    Skills: Python, JavaScript, SQL, Git, Docker, Flask, Data Structures, Algorithms.
    Experience: Developed REST APIs and managed PostgreSQL database integration.
    Projects: Placement preparation portal with AI evaluation modules.
    Certifications: AWS Certified Cloud Practitioner.
    """
    res = detector.detect_language(resume_sample)
    assert res["detected_code"] == "en"
    assert res["detected_language"] == "English"
    assert res["is_supported"] is True
    assert res["requires_warning"] is False
    assert res["confidence"] >= 0.5
    assert "distribution" in res


def test_detect_spanish_resume():
    detector = ResumeLanguageDetector()
    resume_spanish = """
    Currículum Vitae
    Experiencia: Desarrollador de software con experiencia en proyectos de ingeniería.
    Educación: Licenciatura en Ciencias de la Computación, Universidad Nacional.
    Habilidades: Python, desarrollo web, bases de datos relacionales y análisis de datos.
    Responsabilidades: Diseñado e implementado servicios backend para la plataforma educativa.
    """
    res = detector.detect_language(resume_spanish)
    assert res["detected_code"] == "es"
    assert res["detected_language"] == "Spanish"
    assert res["is_supported"] is False
    assert res["requires_warning"] is True
    assert "submitting your resume in English" in res["recommendation"]


def test_detect_french_resume():
    detector = ResumeLanguageDetector()
    resume_french = """
    Curriculum Vitae
    Expérience professionnelle: Ingénieur logiciel spécialisé dans les applications cloud.
    Formation: Diplôme d'ingénieur en informatique, Université de Paris.
    Compétences: Programmation Python, architectures distribuées, conteneurisation Docker.
    Projets: Conçu une plateforme d'évaluation automatisée.
    """
    res = detector.detect_language(resume_french)
    assert res["detected_code"] == "fr"
    assert res["detected_language"] == "French"
    assert res["is_supported"] is False
    assert res["requires_warning"] is True


def test_detect_non_latin_script():
    detector = ResumeLanguageDetector()
    resume_devanagari = """
    बायोडाटा - सॉफ्टवेयर इंजीनियर
    शिक्षा: कंप्यूटर साइंस में स्नातक, दिल्ली विश्वविद्यालय
    कौशल: पायथन, डेटाबेस प्रबंधन, वेब विकास
    अनुभव: बैकएंड सेवाओं का निर्माण किया
    """
    res = detector.detect_language(resume_devanagari)
    assert res["detected_code"] == "non_latin"
    assert "Devanagari" in res["detected_language"]
    assert res["is_supported"] is False
    assert res["requires_warning"] is True


def test_analyze_language_distribution():
    detector = ResumeLanguageDetector()
    mixed = "Summary of experience: education and skills in engineering. proyectos y experiencia laboral."
    dist = detector.analyze_language_distribution(mixed)
    assert dist["total_tokens"] > 0
    assert "en" in dist["keyword_hits"]
    assert "es" in dist["keyword_hits"]


def test_detect_empty_or_whitespace_resume():
    detector = ResumeLanguageDetector()
    res = detector.detect_language("   ")
    assert res["detected_code"] == "unknown"
    assert res["is_supported"] is False
    assert res["requires_warning"] is True


def test_detect_low_content_resume():
    detector = ResumeLanguageDetector()
    res = detector.detect_language("John Doe Resume")
    assert res["detected_code"] == "en"
    assert "Low Content" in res["detected_language"]
    assert res["requires_warning"] is True


def test_api_detect_language_endpoint_success(client):
    res = client.post("/api/resume/detect-language", json={
        "resume_text": "Experienced software developer skilled in Python, algorithms, education, projects, and machine learning."
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["detection"]["detected_code"] == "en"
    assert data["detection"]["is_supported"] is True


def test_api_detect_language_endpoint_empty_error(client):
    res = client.post("/api/resume/detect-language", json={
        "resume_text": ""
    })
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert "error" in data
