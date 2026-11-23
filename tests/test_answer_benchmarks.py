import pytest
from utils.answer_benchmark_service import get_answer_benchmarks, get_benchmark_by_id

def test_get_all_benchmarks():
    benchmarks = get_answer_benchmarks()
    assert len(benchmarks) >= 3
    assert any(b["category"] == "technical" for b in benchmarks)
    assert any(b["category"] == "behavioral" for b in benchmarks)

def test_filter_benchmarks_by_category():
    tech = get_answer_benchmarks(category="technical")
    assert len(tech) >= 1
    assert all(b["category"] == "technical" for b in tech)

def test_search_benchmarks():
    results = get_answer_benchmarks(search="cycle")
    assert len(results) >= 1
    assert "cycle" in results[0]["question"].lower()

def test_get_benchmark_by_id():
    b = get_benchmark_by_id("bench-tech-01")
    assert b is not None
    assert "benchmarks" in b
    assert "good" in b["benchmarks"]
    assert "average" in b["benchmarks"]
    assert "poor" in b["benchmarks"]

def test_benchmark_api_endpoints(client):
    res = client.get("/api/interview/benchmarks?category=technical")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "success"
    assert data["count"] >= 1
    assert data["benchmarks"][0]["category"] == "technical"

    res_single = client.get("/api/interview/benchmarks/bench-tech-01")
    assert res_single.status_code == 200
    data_single = res_single.get_json()
    assert data_single["status"] == "success"
    assert data_single["benchmark"]["id"] == "bench-tech-01"
