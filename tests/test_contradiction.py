"""Tests for ContradictionDetector."""
from __future__ import annotations

import pytest

from lorien.contradiction import ContradictionDetector
from lorien.schema import GraphStore
from lorien.models import Fact


@pytest.fixture
def store(tmp_path):
    return GraphStore(str(tmp_path / "contra_test"))


@pytest.fixture
def detector(store):
    return ContradictionDetector(store=store, vector_index=None, llm_model=None)


class TestHeuristicContradiction:
    def test_korean_like_dislike(self, detector):
        assert detector._heuristic_contradiction("파이썬을 좋아해", "파이썬을 싫어해")

    def test_allow_prohibit(self, detector):
        assert detector._heuristic_contradiction("허용한다", "금지한다")

    def test_always_never(self, detector):
        assert detector._heuristic_contradiction("always use tests", "never use tests")

    def test_must_must_not(self, detector):
        assert detector._heuristic_contradiction("must commit daily", "must not commit untested code")

    def test_no_contradiction(self, detector):
        assert not detector._heuristic_contradiction("I like Python", "Python is fast")

    def test_unrelated_facts(self, detector):
        assert not detector._heuristic_contradiction("The sky is blue", "Pizza is delicious")

    def test_symmetric(self, detector):
        """Contradiction should be detected in both directions."""
        a, b = "always push to main", "never push to main"
        assert detector._heuristic_contradiction(a, b)
        assert detector._heuristic_contradiction(b, a)


class TestCheckAndRecord:
    def test_no_contradiction_empty_db(self, store, detector):
        """Should find 0 contradictions when DB is empty."""
        fact = Fact(text="I like coffee", fact_type="preference")
        store.add_fact(fact)
        count = detector.check_and_record(fact.id, fact.text, node_type="Fact")
        assert count == 0

    def test_detects_contradiction(self, store, detector):
        """Should detect and record a contradiction."""
        fact_a = Fact(text="항상 테스트 코드를 작성해야 한다", fact_type="preference")
        store.add_fact(fact_a)

        fact_b = Fact(text="절대 테스트 코드를 작성하지 말아야 한다", fact_type="preference")
        store.add_fact(fact_b)

        count = detector.check_and_record(fact_b.id, fact_b.text, node_type="Fact")
        assert count >= 1

        # Verify CONTRADICTS edge was created
        rows = store.query(
            f"MATCH (a:Fact)-[:CONTRADICTS]->(b:Fact) "
            f"WHERE a.id = '{fact_b.id}' RETURN b.id"
        )
        assert len(rows) >= 1

    def test_no_false_positives(self, store, detector):
        """Unrelated facts should not be flagged as contradictions."""
        fact_a = Fact(text="User lives in Seoul", fact_type="biographical")
        store.add_fact(fact_a)

        fact_b = Fact(text="User enjoys hiking", fact_type="preference")
        store.add_fact(fact_b)

        count = detector.check_and_record(fact_b.id, fact_b.text, node_type="Fact")
        assert count == 0

    def test_empty_text_skipped(self, store, detector):
        count = detector.check_and_record("some_id", "", node_type="Fact")
        assert count == 0


class TestFromIngester:
    def test_creates_from_ingester(self, store):
        from lorien.ingest import LorienIngester
        ingester = LorienIngester(store)
        detector = ContradictionDetector.from_ingester(ingester)
        assert detector.store is store
        assert detector.llm_model is None
