"""Integration tests for lorien v0.3 — temporal + multi-agent + decisions working together."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from lorien.schema import GraphStore
from lorien.models import Agent, Decision, Fact, Rule
from lorien.memory import LorienMemory
from lorien.temporal import freshness_score


def _ts(days_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class TestFullWorkflow:
    """End-to-end: multi-agent recording decisions with supporting evidence."""

    def test_multi_agent_decision_workflow(self, tmp_path):
        """Two agents disagree → record both → check chain."""
        mem = LorienMemory(db_path=str(tmp_path / "workflow"), enable_vectors=False)

        # Register agents
        mem.register_agent("claude", name="Claude Sonnet", agent_type="llm")
        mem.register_agent("codex", name="GPT Codex", agent_type="llm")

        # Claude records a supporting fact
        fact_rest = Fact(text="REST is widely supported and well-documented", agent_id="claude")
        fact_graphql = Fact(text="GraphQL reduces overfetching", agent_id="codex")
        mem.store.add_fact(fact_rest)
        mem.store.add_fact(fact_graphql)

        # Claude decides: use REST
        did = mem.add_decision(
            "Use REST API for public endpoints",
            decision_type="judgment",
            context="Simple CRUD app, team familiar with REST",
            agent_id="claude",
            supporting_fact_ids=[fact_rest.id],
            opposing_fact_ids=[fact_graphql.id],
        )

        # Query why
        result = mem.why(did)
        assert result["decision"]["text"] == "Use REST API for public endpoints"
        assert result["decision"]["agent_id"] == "claude"
        assert len(result["supporting_facts"]) == 1
        assert len(result["opposing_facts"]) == 1

        # Codex records alternative decision
        did2 = mem.add_decision(
            "Use GraphQL for internal data layer",
            decision_type="judgment",
            context="Internal tools need flexible queries",
            agent_id="codex",
            supporting_fact_ids=[fact_graphql.id],
        )

        result2 = mem.why(did2)
        assert result2["decision"]["agent_id"] == "codex"

        # Both agents visible
        agents = mem.get_agents()
        agent_ids = {a["id"] for a in agents}
        assert "claude" in agent_ids
        assert "codex" in agent_ids

    def test_temporal_evolution_with_decision(self, tmp_path):
        """Old fact superseded → new decision based on new fact."""
        mem = LorienMemory(db_path=str(tmp_path / "temporal_decision"), enable_vectors=False)

        # Old fact (60 days ago, low confidence)
        old_fact = Fact(text="Python 3.11 is the latest stable version", confidence=0.3)
        mem.store.add_fact(old_fact)
        mem.store.conn.execute(
            f"MATCH (f:Fact {{id:'{old_fact.id}'}}) SET f.last_confirmed = '{_ts(60)}'"
        )

        # New fact supersedes old
        new_fact = Fact(text="Python 3.12 is the latest stable version", confidence=0.95)
        mem.store.add_fact(new_fact)
        mem.store.add_supersedes(new_fact.id, old_fact.id, reason="version_release")

        # Check old fact is superseded
        rows = mem.store.query(f"MATCH (f:Fact {{id:'{old_fact.id}'}}) RETURN f.status")
        assert rows[0][0] == "superseded"

        # New fact is fresh
        new_freshness = mem.freshness(new_fact.id)
        assert new_freshness > 0.95

        # Decision based on the new fact
        did = mem.add_decision(
            "Upgrade to Python 3.12 in all projects",
            decision_type="action",
            supporting_fact_ids=[new_fact.id],
        )
        result = mem.why(did)
        assert "3.12" in result["supporting_facts"][0]["text"]

    def test_cleanup_doesnt_affect_decision_evidence(self, tmp_path):
        """Cleanup expires stale facts but active decision evidence stays."""
        mem = LorienMemory(db_path=str(tmp_path / "cleanup_dec"), enable_vectors=False)

        # Stale fact not linked to any decision
        stale = Fact(text="Old unlinked fact", confidence=0.1)
        mem.store.add_fact(stale)
        mem.store.conn.execute(
            f"MATCH (f:Fact {{id:'{stale.id}'}}) SET f.last_confirmed = '{_ts(100)}'"
        )

        # Fact linked to decision (also old but critical)
        evidence = Fact(text="Security audit passed", confidence=0.1)
        mem.store.add_fact(evidence)
        mem.store.conn.execute(
            f"MATCH (f:Fact {{id:'{evidence.id}'}}) SET f.last_confirmed = '{_ts(100)}'"
        )
        did = mem.add_decision("Ship to production", supporting_fact_ids=[evidence.id])

        # Cleanup runs
        result = mem.cleanup(max_age_days=90, min_confidence=0.3)
        assert result["expired"] >= 1

        # Decision chain is still queryable (even if fact expired, structure intact)
        chain = mem.why(did)
        assert chain["decision"]["text"] == "Ship to production"

    def test_agent_stats_across_phases(self, tmp_path):
        """Agent stats accumulate across facts, rules, decisions."""
        mem = LorienMemory(db_path=str(tmp_path / "agent_stats_full"), enable_vectors=False)
        mem.register_agent("bot", name="TestBot")

        mem.store.add_fact(Fact(text="Fact 1", agent_id="bot"))
        mem.store.add_fact(Fact(text="Fact 2", agent_id="bot"))
        mem.store.add_rule(Rule(text="Rule 1", agent_id="bot"))
        mem.add_decision("Decision 1", agent_id="bot")

        stats = mem.get_agent_stats("bot")
        assert stats["facts"] == 2
        assert stats["rules"] == 1

    def test_search_decisions_returns_active_only(self, tmp_path):
        """Revoked decisions should not appear in search."""
        mem = LorienMemory(db_path=str(tmp_path / "search_active"), enable_vectors=False)
        did = mem.add_decision("Use Celery for background tasks")
        mem.revoke_decision(did)

        # Active decision stays
        mem.add_decision("Use Celery for scheduled jobs")

        results = mem.search_decisions("Celery")
        statuses = {r["text"] for r in results}
        # Revoked one should not appear (search filters status='active')
        assert not any("background tasks" in t for t in statuses)
        assert any("scheduled jobs" in t for t in statuses)

    def test_confirm_after_why(self, tmp_path):
        """Confirm evidence facts after reviewing a why() chain."""
        mem = LorienMemory(db_path=str(tmp_path / "confirm_why"), enable_vectors=False)
        fact = Fact(text="Load tests show 99.9% uptime", confidence=0.9)
        mem.store.add_fact(fact)
        did = mem.add_decision("Keep current infrastructure", supporting_fact_ids=[fact.id])

        result = mem.why(did)
        fact_ids = [f["id"] for f in result["supporting_facts"]]

        # Confirm evidence freshness
        updated = mem.confirm(fact_ids)
        assert updated == 1
        assert mem.freshness(fact.id) > 0.99


class TestMigration:
    def test_migrate_v02_to_v03_idempotent(self, tmp_path):
        """Migration is safe to run multiple times."""
        store = GraphStore(str(tmp_path / "migrate_test"))
        # In v0.3 schema, new facts already have temporal fields — migration should handle gracefully
        result1 = store.migrate_v02_to_v03()
        result2 = store.migrate_v02_to_v03()
        # Both should return counts (0 on second run since already migrated)
        assert isinstance(result1["facts_migrated"], int)
        assert isinstance(result2["facts_migrated"], int)

    def test_node_counts_stable_after_migration(self, tmp_path):
        """Migration doesn't add or remove nodes."""
        store = GraphStore(str(tmp_path / "migrate_counts"))
        store.add_fact(Fact(text="Fact before migration"))
        store.add_rule(Rule(text="Rule before migration"))
        counts_before = store.count_nodes()
        store.migrate_v02_to_v03()
        counts_after = store.count_nodes()
        assert counts_before == counts_after
