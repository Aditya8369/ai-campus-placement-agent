import tempfile
from pathlib import Path

import config
from utils.database import (
    create_interview_session,
    delete_analysis,
    get_analysis,
    get_db_connection,
    get_interview_session,
    get_recent_analyses,
    init_db,
    save_analysis,
    update_interview_session,
)


def test_database_lifecycle(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test_placement.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db_path)

        init_db()
        assert test_db_path.exists()

        analysis_id = "test-uuid-1234"
        sample_results = {
            "resume_analysis": {"ats_score": 85},
            "job_match": {"match_percentage": 90},
        }
        save_analysis(
            analysis_id=analysis_id,
            resume_filename="resume.pdf",
            company_name="Google",
            job_description="Python SDE",
            results_dict=sample_results,
        )

        record = get_analysis(analysis_id)
        assert record is not None
        assert record["company_name"] == "Google"
        assert record["results"]["resume_analysis"]["ats_score"] == 85

        questions = [{"index": 0, "type": "HR", "question": "Tell me about yourself."}]
        create_interview_session(analysis_id, analysis_id, questions)

        session = get_interview_session(analysis_id)
        assert session is not None
        assert len(session["questions"]) == 1
        assert session["completed"] == 0

        update_interview_session(
            interview_id=analysis_id,
            current_question_index=1,
            answers_list=[{"question_index": 0, "answer": "Here is my background."}],
            completed=True,
        )

        updated_session = get_interview_session(analysis_id)
        assert updated_session["completed"] == 1
        assert len(updated_session["answers"]) == 1


def test_recent_analyses_and_deletion(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test_placement.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db_path)

        init_db()

        # Save 3 records
        for i in range(1, 4):
            save_analysis(
                analysis_id=f"id-{i}",
                resume_filename=f"resume_{i}.pdf",
                company_name=f"Company {i}",
                job_description="Engineer",
                results_dict={
                    "resume_analysis": {"ats_score": 70 + i * 5},
                    "job_match": {"match_percentage": 80 + i},
                },
            )

        recent = get_recent_analyses(limit=2)
        assert len(recent) == 2
        assert "ats_score" in recent[0]
        assert "match_percentage" in recent[0]

        # Test deletion
        assert delete_analysis("id-2") is True
        assert get_analysis("id-2") is None
        # Deleting non-existent returns False
        assert delete_analysis("id-999") is False


def test_database_indexes_created(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = Path(tmpdir) / "test_placement.db"
        monkeypatch.setattr(config, "DATABASE_PATH", test_db_path)

        init_db()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row["name"] for row in cursor.fetchall()}
        conn.close()

        assert "idx_analyses_created_at" in indexes
        assert "idx_interviews_analysis_id" in indexes


def test_database_facade_all_exports_bound():
    """
    Regression test for #834: Ensure every symbol declared in utils.database.__all__
    is bound and resolvable on the module namespace.
    """
    import utils.database as db

    missing = [name for name in db.__all__ if not hasattr(db, name)]
    assert not missing, f"Unbound symbols declared in utils.database.__all__: {missing}"


def test_database_facade_helpful_vote_exports():
    """
    Regression test for #834: Ensure interview helpful vote functions
    are properly exposed through the utils.database facade.
    """
    from utils.database import (
        check_voting_rate_limit,
        get_contributor_helped_students_count,
        get_user_helpful_votes,
        toggle_helpful_vote,
    )
    import utils.interview_helpful_service as helpful_service

    assert callable(toggle_helpful_vote)
    assert callable(get_user_helpful_votes)
    assert callable(get_contributor_helped_students_count)
    assert callable(check_voting_rate_limit)

    assert toggle_helpful_vote is helpful_service.toggle_helpful_vote
    assert get_user_helpful_votes is helpful_service.get_user_helpful_votes
    assert get_contributor_helped_students_count is helpful_service.get_contributor_helped_students_count
    assert check_voting_rate_limit is helpful_service.check_voting_rate_limit


def test_database_wildcard_import_and_app_startup():
    """
    Regression test for #834: Verify that wildcard import from utils.database
    executes without AttributeError and does not block application startup.
    """
    namespace = {}
    exec("from utils.database import *", namespace)

    assert "toggle_helpful_vote" in namespace
    assert "get_user_helpful_votes" in namespace
    assert "get_contributor_helped_students_count" in namespace
    assert "check_voting_rate_limit" in namespace
