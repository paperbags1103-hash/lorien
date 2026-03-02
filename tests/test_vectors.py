"""Tests for VectorIndex — requires sentence-transformers (slow first run for model download)."""
from __future__ import annotations

import pytest
import numpy as np

pytest.importorskip("sentence_transformers", reason="sentence-transformers not installed")


@pytest.fixture
def vidx(tmp_path):
    from lorien.vectors import VectorIndex
    # Use tiny model for speed in tests
    return VectorIndex(str(tmp_path / "test_db"), model_name="paraphrase-multilingual-MiniLM-L12-v2")


class TestVectorIndexBasics:
    def test_add_and_count(self, vidx):
        vidx.add("fact_001", "Fact", "The user likes coffee")
        assert vidx.count() == 1
        assert vidx.count("Fact") == 1
        assert vidx.count("Rule") == 0

    def test_add_multiple(self, vidx):
        vidx.add("f1", "Fact", "User prefers Python over Java")
        vidx.add("f2", "Fact", "User dislikes meetings")
        vidx.add("r1", "Rule", "Never book morning meetings")
        assert vidx.count() == 3

    def test_add_empty_text_skipped(self, vidx):
        vidx.add("x1", "Fact", "")
        vidx.add("x2", "Fact", "   ")
        assert vidx.count() == 0

    def test_remove(self, vidx):
        vidx.add("f1", "Fact", "Some fact")
        assert vidx.count() == 1
        vidx.remove("f1")
        assert vidx.count() == 0

    def test_upsert(self, vidx):
        vidx.add("f1", "Fact", "First text")
        vidx.add("f1", "Fact", "Updated text")  # OR REPLACE
        assert vidx.count() == 1


class TestVectorSearch:
    def test_search_returns_list(self, vidx):
        vidx.add("f1", "Fact", "The user is allergic to shellfish")
        results = vidx.search("seafood allergy")
        assert isinstance(results, list)

    def test_search_empty_index(self, vidx):
        results = vidx.search("anything")
        assert results == []

    def test_search_empty_query(self, vidx):
        vidx.add("f1", "Fact", "Some fact")
        results = vidx.search("")
        assert results == []

    def test_semantic_similarity(self, vidx):
        """Semantic search: 'shellfish allergy' should find 'allergic to oysters'."""
        vidx.add("f1", "Fact", "User is allergic to oysters and clams")
        vidx.add("f2", "Fact", "User loves hiking on weekends")
        results = vidx.search("shellfish allergy", top_k=5)
        assert len(results) > 0
        # The allergy fact should score higher than hiking
        if len(results) >= 2:
            allergy_result = next((r for r in results if "allergic" in r["text"]), None)
            hiking_result = next((r for r in results if "hiking" in r["text"]), None)
            if allergy_result and hiking_result:
                assert allergy_result["score"] > hiking_result["score"]

    def test_search_filter_by_type(self, vidx):
        vidx.add("f1", "Fact", "User prefers Python")
        vidx.add("r1", "Rule", "Never use deprecated Python APIs")
        fact_results = vidx.search("Python", node_type="Fact")
        rule_results = vidx.search("Python", node_type="Rule")
        assert all(r["node_type"] == "Fact" for r in fact_results)
        assert all(r["node_type"] == "Rule" for r in rule_results)

    def test_search_result_structure(self, vidx):
        vidx.add("f1", "Fact", "User works at a tech company")
        results = vidx.search("technology job", top_k=1)
        if results:
            r = results[0]
            assert "id" in r
            assert "text" in r
            assert "node_type" in r
            assert "score" in r
            assert 0.0 <= r["score"] <= 1.0

    def test_search_threshold(self, vidx):
        vidx.add("f1", "Fact", "The sky is blue")
        # Search for very unrelated topic — should return nothing above threshold
        results = vidx.search("quantum mechanics orbital equations", threshold=0.9)
        assert results == []

    def test_search_top_k(self, vidx):
        for i in range(10):
            vidx.add(f"f{i}", "Fact", f"Fact number {i} about programming")
        results = vidx.search("programming", top_k=3)
        assert len(results) <= 3


class TestSimilarTo:
    def test_similar_to_existing(self, vidx):
        vidx.add("f1", "Fact", "User is allergic to shellfish")
        vidx.add("f2", "Fact", "User cannot eat seafood")
        vidx.add("f3", "Fact", "User loves hiking")
        results = vidx.similar_to("f1", top_k=2)
        assert isinstance(results, list)
        # f1 should not appear in its own similar results
        assert all(r["id"] != "f1" for r in results)

    def test_similar_to_nonexistent(self, vidx):
        results = vidx.similar_to("nonexistent_id")
        assert results == []
