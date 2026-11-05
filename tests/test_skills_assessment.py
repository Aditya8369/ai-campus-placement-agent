import pytest
from unittest.mock import patch
import config
from app import app
from utils.database import (
    init_db,
    save_skill_self_assessment,
    get_student_skill_self_assessments,
    delete_skill_self_assessment,
    get_default_technical_skills_catalog
)

@pytest.fixture
def client(tmp_path):
    test_db = tmp_path / "test_skills.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        app.config["TESTING"] = True
        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user_id"] = "default_student"
                sess["user_name"] = "Default Student"
            yield client

def test_database_skill_self_assessment_crud(tmp_path):
    test_db = tmp_path / "test_crud.db"
    with patch.object(config, "DATABASE_PATH", str(test_db)):
        init_db()
        student_id = "test_student_skill_01"
        
        # Verify catalog returns expected domains
        catalog = get_default_technical_skills_catalog()
        assert "Programming Languages" in catalog
        assert "SQL" in catalog["Data & Databases"]

        # 1. Insert assessment
        res1 = save_skill_self_assessment(
            student_id=student_id,
            skill_name="Python",
            category="Programming Languages",
            proficiency_level="Advanced",
            years_experience=2.5,
            notes="Proficient with Flask, PyTorch, OOP."
        )
        assert res1["skill_name"] == "Python"
        assert res1["proficiency_level"] == "Advanced"

        # 2. Update same skill
        res2 = save_skill_self_assessment(
            student_id=student_id,
            skill_name="Python",
            category="Programming Languages",
            proficiency_level="Expert",
            years_experience=3.0,
            notes="Updated: Led AI team project."
        )
        assert res2["proficiency_level"] == "Expert"

        # 3. Add second skill
        save_skill_self_assessment(
            student_id=student_id,
            skill_name="Docker",
            category="Cloud & DevOps",
            proficiency_level="Intermediate",
            years_experience=1.0,
            notes="Created multi-stage Dockerfiles."
        )

        items = get_student_skill_self_assessments(student_id)
        assert len(items) == 2
        skill_names = [it["skill_name"] for it in items]
        assert "Python" in skill_names
        assert "Docker" in skill_names

        # 4. Delete skill
        deleted = delete_skill_self_assessment(student_id, "Docker")
        assert deleted is True
        remaining = get_student_skill_self_assessments(student_id)
        assert len(remaining) == 1
        assert remaining[0]["skill_name"] == "Python"


def test_skills_assessment_endpoints(client):
    # GET page view
    res = client.get("/skills-assessment")
    assert res.status_code == 200
    assert b"Technical Skills Self-Assessment" in res.data
    assert b"Programming Languages" in res.data

    # POST new skill assessment via form
    post_res = client.post(
        "/skills-assessment",
        data={
            "skill_name": "PostgreSQL",
            "category": "Data & Databases",
            "proficiency_level": "Advanced",
            "years_experience": "2",
            "notes": "Query optimization, indexing"
        },
        follow_redirects=True
    )
    assert post_res.status_code == 200
    assert b"PostgreSQL" in post_res.data

    # Test API GET
    api_get = client.get("/api/skills-assessment?student_id=default_student")
    assert api_get.status_code == 200
    data = api_get.get_json()
    assert data["status"] == "success"
    assert any(s["skill_name"] == "PostgreSQL" for s in data["skills"])

    # Test API POST
    api_post = client.post(
        "/api/skills-assessment",
        json={
            "student_id": "api_test_student",
            "skill_name": "Kubernetes",
            "category": "Cloud & DevOps",
            "proficiency_level": "Intermediate",
            "years_experience": 1.5,
            "notes": "Deployed pods and services"
        }
    )
    assert api_post.status_code == 201
    assert api_post.get_json()["status"] == "success"

    # Test API DELETE
    api_del = client.delete(
        "/api/skills-assessment",
        json={
            "student_id": "api_test_student",
            "skill_name": "Kubernetes"
        }
    )
    assert api_del.status_code == 200
    assert api_del.get_json()["status"] == "success"
