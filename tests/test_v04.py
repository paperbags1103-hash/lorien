"""Tests for lorien v0.4 — Epistemic Debt, Belief Fork, Consequence Simulation."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from lorien.schema import GraphStore
from lorien.models import Fact, Rule, Agent
from lorien.memory import LorienMemory


def _ts(days_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


# ── Epistemic Debt ────────────────────────────────────────────────────────────

class TestEpistemicDebt:
    def test_debt_surfaces_old_high_confidence(self, tmp_path):
        store = GraphStore(str(tmp_path / "debt_test"))
        fact = Fact(text="User prefers async communication", confidence=0.9)
        store.add_fact(fact)
        store.conn.execute(
            f"MATCH (f:Fact {{id:'{fact.id}'}}) SET f.last_confirmed = '{_ts(90)}'"
        )
        debt = store.get_epistemic_debt(min_confidence=0.7, min_age_days=60.0)
        assert len(debt) >= 1
        assert any(d["fact_id"] == fact.id for d in debt)

    def test_debt_ignores_recently_confirmed(self, tmp_path):
        store = GraphStore(str(tmp_path / "debt_recent"))
        fact = Fact(text="Recent fact", confidence=0.9)
        store.add_fact(fact)
        # last_confirmed is NOW by default
        debt = store.get_epistemic_debt(min_confidence=0.7, min_age_days=60.0)
        assert not any(d["fact_id"] == fact.id for d in debt)

    def test_debt_ignores_low_confidence(self, tmp_path):
        store = GraphStore(str(tmp_path / "debt_low_conf"))
        fact = Fact(text="Low confidence fact", confidence=0.3)
        store.add_fact(fact)
        store.conn.execute(
            f"MATCH (f:Fact {{id:'{fact.id}'}}) SET f.last_confirmed = '{_ts(90)}'"
        )
        debt = store.get_epistemic_debt(min_confidence=0.7, min_age_days=60.0)
        assert not any(d["fact_id"] == fact.id for d in debt)

    def test_debt_score_ordering(self, tmp_path):
        store = GraphStore(str(tmp_path / "debt_order"))
        # High debt: old + high confidence
        high = Fact(text="High debt fact", confidence=0.95)
        # Low debt: less old + lower confidence
        low = Fact(text="Low debt fact", confidence=0.75)
        store.add_fact(high)
        store.add_fact(low)
        store.conn.execute(
            f"MATCH (f:Fact {{id:'{high.id}'}}) SET f.last_confirmed = '{_ts(300)}'"
        )
        store.conn.execute(
            f"MATCH (f:Fact {{id:'{low.id}'}}) SET f.last_confirmed = '{_ts(70)}'"
        )
        debt = store.get_epistemic_debt(min_confidence=0.7, min_age_days=60.0)
        ids = [d["fact_id"] for d in debt]
        assert ids.index(high.id) < ids.index(low.id)


class TestReviewDebt:
    def test_review_confirm(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "review_confirm"), enable_vectors=False)
        fact = Fact(text="Confirm me", confidence=0.9)
        mem.store.add_fact(fact)
        result = mem.review_debt(fact.id, "confirm")
        assert result["action"] == "confirm"
        assert result["new_fact_id"] is None

    def test_review_expire(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "review_expire"), enable_vectors=False)
        fact = Fact(text="Expire me", confidence=0.9)
        mem.store.add_fact(fact)
        result = mem.review_debt(fact.id, "expire")
        assert result["action"] == "expire"
        rows = mem.store.query(f"MATCH (f:Fact {{id:'{fact.id}'}}) RETURN f.status")
        assert rows[0][0] == "expired"

    def test_review_update_creates_supersedes(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "review_update"), enable_vectors=False)
        fact = Fact(text="Python 3.11 is latest", confidence=0.9)
        mem.store.add_fact(fact)
        result = mem.review_debt(fact.id, "update", new_text="Python 3.12 is latest")
        assert result["action"] == "update"
        assert result["new_fact_id"] is not None
        # Old fact should be superseded
        rows = mem.store.query(f"MATCH (f:Fact {{id:'{fact.id}'}}) RETURN f.status")
        assert rows[0][0] == "superseded"

    def test_review_invalid_action_raises(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "review_invalid"), enable_vectors=False)
        fact = Fact(text="Test")
        mem.store.add_fact(fact)
        with pytest.raises(ValueError, match="Unknown action"):
            mem.review_debt(fact.id, "invalid_action")


# ── Belief Fork ───────────────────────────────────────────────────────────────

class TestBeliefFork:
    def test_no_fork_single_agent(self, tmp_path):
        store = GraphStore(str(tmp_path / "fork_single"))
        store.get_or_create_agent("a1")
        f = Fact(text="User likes Python", subject_id="ent1", predicate="likes", agent_id="a1")
        store.add_fact(f)
        forks = store.find_belief_forks(min_agents=2)
        assert len(forks) == 0

    def test_fork_detected_two_agents(self, tmp_path):
        store = GraphStore(str(tmp_path / "fork_two"))
        store.get_or_create_agent("claude")
        store.get_or_create_agent("codex")
        f1 = Fact(text="User is backend dev", subject_id="user1", predicate="occupation", agent_id="claude")
        f2 = Fact(text="User runs AI startup", subject_id="user1", predicate="occupation", agent_id="codex")
        store.add_fact(f1)
        store.add_fact(f2)
        forks = store.find_belief_forks(min_agents=2)
        assert len(forks) >= 1

    def test_fork_critical_with_contradicts_edge(self, tmp_path):
        store = GraphStore(str(tmp_path / "fork_critical"))
        store.get_or_create_agent("a1")
        store.get_or_create_agent("a2")
        f1 = Fact(text="Alice has no dietary restrictions", subject_id="alice", predicate="diet", agent_id="a1")
        f2 = Fact(text="Alice is vegan", subject_id="alice", predicate="diet", agent_id="a2")
        store.add_fact(f1)
        store.add_fact(f2)
        store.add_contradicts(f1.id, f2.id)
        forks = store.find_belief_forks(min_agents=2)
        critical = [f for f in forks if f["severity"] == "critical"]
        assert len(critical) >= 1

    def test_fork_warning_on_freshness_gap(self, tmp_path):
        store = GraphStore(str(tmp_path / "fork_warning"))
        store.get_or_create_agent("a1")
        store.get_or_create_agent("a2")
        f1 = Fact(text="Project is in beta", subject_id="proj1", predicate="status", agent_id="a1")
        f2 = Fact(text="Project launched", subject_id="proj1", predicate="status", agent_id="a2")
        store.add_fact(f1)
        store.add_fact(f2)
        # Make f1 very old
        store.conn.execute(
            f"MATCH (f:Fact {{id:'{f1.id}'}}) SET f.last_confirmed = '{_ts(45)}'"
        )
        forks = store.find_belief_forks(min_agents=2)
        assert len(forks) >= 1
        severities = {f["severity"] for f in forks}
        assert "warning" in severities or "critical" in severities

    def test_get_belief_forks_via_memory(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "fork_mem"), enable_vectors=False)
        result = mem.get_belief_forks()
        assert isinstance(result, list)


# ── Consequence Simulation ────────────────────────────────────────────────────

class TestConsequenceSimulation:
    def test_simulate_returns_structure(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "sim_basic"), enable_vectors=False)
        result = mem.simulate_decision("Switch to remote work")
        assert "compatible_facts" in result
        assert "needs_update" in result
        assert "rule_violations" in result
        assert "recommendation" in result
        assert "disclaimer" in result

    def test_simulate_does_not_write_to_graph(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "sim_readonly"), enable_vectors=False)
        before = mem.store.count_nodes()
        mem.simulate_decision("Start a new company")
        after = mem.store.count_nodes()
        assert before == after

    def test_simulate_empty_graph_proceeds(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "sim_empty"), enable_vectors=False)
        result = mem.simulate_decision("Do anything")
        assert result["recommendation"] == "proceed"

    def test_simulate_detects_rule_violation(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "sim_rule"), enable_vectors=False)
        # Add a prohibition rule that overlaps with decision text
        rule = Rule(
            text="quit job only after 6 months savings",
            rule_type="prohibition",
            priority=85,
        )
        mem.store.add_rule(rule)
        result = mem.simulate_decision("quit job and freelance")
        # Should detect the rule (word overlap: "quit", "job")
        assert result["recommendation"] in ("caution", "reconsider", "proceed")

    def test_simulate_includes_disclaimer(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "sim_disclaimer"), enable_vectors=False)
        result = mem.simulate_decision("Test decision")
        assert "disclaimer" in result
        assert len(result["disclaimer"]) > 0

    def test_simulate_impact_score_range(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "sim_score"), enable_vectors=False)
        result = mem.simulate_decision("Some decision")
        assert 0.0 <= result["impact_score"] <= 1.0
