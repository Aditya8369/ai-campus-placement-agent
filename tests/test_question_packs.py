import pytest
from utils.question_pack_service import (
    create_question_pack,
    get_user_question_packs,
    get_question_pack_by_id,
    delete_question_pack
)

def test_create_and_get_question_pack():
    user_id = "test_user_pack_1"
    questions = [
        {"text": "What is dependency injection?", "type": "technical"},
        "Tell me about a time you led a team project."
    ]
    res = create_question_pack(
        user_id=user_id,
        title="My Custom Backend Practice",
        questions=questions,
        category="technical"
    )
    assert res["success"] is True
    pack = res["pack"]
    assert pack["title"] == "My Custom Backend Practice"
    assert pack["questions_count"] == 2
    pack_id = pack["id"]

    # Retrieve all
    user_packs = get_user_question_packs(user_id)
    assert len(user_packs) >= 1
    assert user_packs[0]["id"] == pack_id

    # Retrieve single
    single = get_question_pack_by_id(pack_id, user_id)
    assert single is not None
    assert single["title"] == "My Custom Backend Practice"

    # Privacy check (other user cannot read)
    assert get_question_pack_by_id(pack_id, "other_user") is None

    # Delete
    deleted = delete_question_pack(pack_id, user_id)
    assert deleted is True
    assert get_question_pack_by_id(pack_id, user_id) is None

def test_create_question_pack_validation():
    res = create_question_pack(user_id="", title="Test", questions=["Q1"])
    assert res["success"] is False

    res_empty_q = create_question_pack(user_id="user1", title="Test", questions=[])
    assert res_empty_q["success"] is False

def test_question_pack_api(client):
    # Create pack via API
    res = client.post("/api/interview/question-packs", json={
        "title": "API Automation Pack",
        "category": "qa",
        "questions": ["How does pytest fixture scope work?", "What is mock testing?"]
    })
    assert res.status_code == 201
    data = res.get_json()
    assert data["status"] == "success"
    pack_id = data["pack"]["id"]

    # List packs
    list_res = client.get("/api/interview/question-packs")
    assert list_res.status_code == 200
    list_data = list_res.get_json()
    assert list_data["status"] == "success"
    assert any(p["id"] == pack_id for p in list_data["packs"])

    # Delete pack
    del_res = client.delete(f"/api/interview/question-packs/{pack_id}")
    assert del_res.status_code == 200
