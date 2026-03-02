"""Tests for temporal tagging and freshness scoring (lorien v0.3)."""
from __future__ import annotations

import time
from datetime import datetime, timezone, timedelta

import pytest

from lorien.schema import GraphStore
from lorien.models import Fact, Rule
from lorien.temporal import freshness_score, is_stale, classify_temporal_relation, age_in_days
from lorien.memory import LorienMemory


def _ts(days_ago: float = 0.0) -> str:
    """Return an ISO UTC timestamp N days ago."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# ── freshness_score ───────────────────────────────────────────────────────────

class TestFreshnessScore:
    def test_just_confirmed_is_near_one(self):
        score = freshness_score(_ts(0))
        assert score > 0.99

    def test_half_life_30_days(self):
        score = freshness_score(_ts(30))
        assert 0.45 < score < 0.55  # ≈ 0.5

    def test_90_days_very_low(self):
        score = freshness_score(_ts(90))
        assert score < 0.2

    def test_empty_string_returns_neutral(self):
        assert freshness_score("") == 0.5

    def test_invalid_returns_neutral(self):
        assert freshness_score("not-a-date") == 0.5

    def test_monotonically_decreasing(self):
        scores = [freshness_score(_ts(d)) for d in [0, 7, 14, 30, 60, 90]]
        assert all(a > b for a, b in zip(scores, scores[1:]))


# ── is_stale ─────────────────────────────────────────────────────────────────

class TestIsStale:
    def test_old_low_confidence_is_stale(self):
        assert is_stale(_ts(91), max_age_days=90, min_confidence=0.3, confidence=0.2)

    def test_old_high_confidence_not_stale(self):
        assert not is_stale(_ts(91), max_age_days=90, min_confidence=0.3, confidence=0.9)

    def test_recent_low_confidence_not_stale(self):
        assert not is_stale(_ts(1), max_age_days=90, min_confidence=0.3, confidence=0.1)

    def test_empty_timestamp_not_stale(self):
        assert not is_stale("", max_age_days=90, min_confidence=0.3, confidence=0.1)


# ── classify_temporal_relation ────────────────────────────────────────────────

class TestClassifyTemporalRelation:
    def test_same_subject_predicate_large_gap_is_evolution(self):
        result = classify_temporal_relation(
            "User loves Python", _ts(60),
            "User hates Python", _ts(0),
            same_subject_predicate=True,
            time_gap_threshold_days=7.0,
        )
        assert result == "evolution"

    def test_same_time_is_contradiction(self):
        result = classify_temporal_relation(
            "User loves Python", _ts(0),
            "User hates Python", _ts(0),
            same_subject_predicate=True,
            time_gap_threshold_days=7.0,
        )
        assert result == "contradiction"

    def test_different_subject_predicate_is_contradiction(self):
        result = classify_temporal_relation(
            "User loves Python", _ts(60),
            "User hates Python", _ts(0),
            same_subject_predicate=False,
        )
        assert result == "contradiction"

    def test_empty_text_is_unrelated(self):
        assert classify_temporal_relation("", _ts(0), "", _ts(0)) == "unrelated"


# ── GraphStore temporal methods ───────────────────────────────────────────────

class TestGraphStoreTemporal:
    def test_fact_has_temporal_fields(self, tmp_path):
        store = GraphStore(str(tmp_path / "temporal_test"))
        fact = Fact(text="User likes hiking", fact_type="preference")
        store.add_fact(fact)
        rows = store.query(
            f"MATCH (f:Fact {{id:'{fact.id}'}}) "
            f"RETURN f.last_confirmed, f.expires_at, f.version"
        )
        assert rows
        last_confirmed, expires_at, version = rows[0]
        assert last_confirmed  # not empty
        assert expires_at == ""  # never expires by default
        assert version == 1

    def test_rule_has_temporal_fields(self, tmp_path):
        store = GraphStore(str(tmp_path / "temporal_rule_test"))
        rule = Rule(text="Always write tests", rule_type="instruction", priority=80)
        store.add_rule(rule)
        rows = store.query(
            f"MATCH (r:Rule {{id:'{rule.id}'}}) "
            f"RETURN r.last_confirmed, r.expires_at"
        )
        assert rows
        last_confirmed, expires_at = rows[0]
        assert last_confirmed
        assert expires_at == ""

    def test_confirm_fact_updates_timestamp(self, tmp_path):
        store = GraphStore(str(tmp_path / "confirm_test"))
        fact = Fact(text="Test fact", fact_type="statement")
        store.add_fact(fact)
        old_ts = store.query(f"MATCH (f:Fact {{id:'{fact.id}'}}) RETURN f.last_confirmed")[0][0]
        time.sleep(0.01)
        store.confirm_fact(fact.id)
        new_ts = store.query(f"MATCH (f:Fact {{id:'{fact.id}'}}) RETURN f.last_confirmed")[0][0]
        assert new_ts >= old_ts

    def test_add_supersedes_marks_old_as_superseded(self, tmp_path):
        store = GraphStore(str(tmp_path / "supersedes_test"))
        old_fact = Fact(text="User prefers Python 3.11", fact_type="preference")
        new_fact = Fact(text="User prefers Python 3.12", fact_type="preference")
        store.add_fact(old_fact)
        store.add_fact(new_fact)
        store.add_supersedes(new_fact.id, old_fact.id, reason="version_update")
        # Old fact should be superseded
        rows = store.query(f"MATCH (f:Fact {{id:'{old_fact.id}'}}) RETURN f.status")
        assert rows[0][0] == "superseded"
        # SUPERSEDES edge should exist
        edge_rows = store.query(
            f"MATCH (a:Fact)-[:SUPERSEDES]->(b:Fact) "
            f"WHERE a.id = '{new_fact.id}' RETURN b.id"
        )
        assert edge_rows[0][0] == old_fact.id

    def test_expire_stale_facts(self, tmp_path):
        store = GraphStore(str(tmp_path / "expire_test"))
        # Create a stale fact (old last_confirmed, low confidence)
        stale = Fact(text="Old fact", fact_type="statement", confidence=0.1)
        store.add_fact(stale)
        # Manually set last_confirmed to 100 days ago
        old_ts = _ts(100)
        store.conn.execute(
            f"MATCH (f:Fact {{id:'{stale.id}'}}) SET f.last_confirmed = '{old_ts}'"
        )
        expired = store.expire_stale_facts(max_age_days=90, min_confidence=0.3)
        assert expired >= 1
        rows = store.query(f"MATCH (f:Fact {{id:'{stale.id}'}}) RETURN f.status")
        assert rows[0][0] == "expired"

    def test_expire_does_not_touch_high_confidence(self, tmp_path):
        store = GraphStore(str(tmp_path / "no_expire_test"))
        fresh_fact = Fact(text="Important fact", fact_type="statement", confidence=0.9)
        store.add_fact(fresh_fact)
        old_ts = _ts(100)
        store.conn.execute(
            f"MATCH (f:Fact {{id:'{fresh_fact.id}'}}) SET f.last_confirmed = '{old_ts}'"
        )
        expired = store.expire_stale_facts(max_age_days=90, min_confidence=0.3)
        assert expired == 0
        rows = store.query(f"MATCH (f:Fact {{id:'{fresh_fact.id}'}}) RETURN f.status")
        assert rows[0][0] == "active"


# ── LorienMemory temporal API ─────────────────────────────────────────────────

class TestLorienMemoryTemporal:
    def test_confirm_updates_facts(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_confirm"), enable_vectors=False)
        from lorien.models import Fact
        fact = Fact(text="Confirmed fact", fact_type="preference")
        mem.store.add_fact(fact)
        n = mem.confirm([fact.id])
        assert n == 1

    def test_confirm_empty_list(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_confirm2"), enable_vectors=False)
        assert mem.confirm([]) == 0

    def test_freshness_new_fact(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_fresh"), enable_vectors=False)
        fact = Fact(text="Fresh fact", fact_type="statement")
        mem.store.add_fact(fact)
        score = mem.freshness(fact.id)
        assert score > 0.99

    def test_freshness_nonexistent_returns_zero(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_fresh2"), enable_vectors=False)
        assert mem.freshness("nonexistent_id") == 0.0

    def test_cleanup_returns_dict(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_cleanup"), enable_vectors=False)
        result = mem.cleanup()
        assert "expired" in result
        assert isinstance(result["expired"], int)
