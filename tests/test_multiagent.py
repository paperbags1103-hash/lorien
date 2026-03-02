"""Tests for multi-agent shared memory (lorien v0.3 Phase 2)."""
from __future__ import annotations

import time
import threading

import pytest

from lorien.schema import GraphStore
from lorien.models import Agent, Fact, Rule
from lorien.memory import LorienMemory
from lorien.concurrency import WriteQueue


# ── Agent node ────────────────────────────────────────────────────────────────

class TestAgentNode:
    def test_add_agent(self, tmp_path):
        store = GraphStore(str(tmp_path / "agent_test"))
        agent = Agent(id="agent-claude", name="claude-sonnet", agent_type="llm")
        store.add_agent(agent)
        rows = store.query(
            "MATCH (a:Agent {id:'agent-claude'}) RETURN a.name, a.agent_type, a.status"
        )
        assert rows
        name, atype, status = rows[0]
        assert name == "claude-sonnet"
        assert atype == "llm"
        assert status == "active"

    def test_get_or_create_agent_creates_new(self, tmp_path):
        store = GraphStore(str(tmp_path / "goc_test"))
        result = store.get_or_create_agent("new-agent", name="Codex", agent_type="llm")
        assert result["id"] == "new-agent"
        assert result["name"] == "Codex"

    def test_get_or_create_agent_returns_existing(self, tmp_path):
        store = GraphStore(str(tmp_path / "goc_exist_test"))
        store.get_or_create_agent("existing", name="Claude", agent_type="llm")
        result = store.get_or_create_agent("existing", name="Different Name")
        # Should return existing agent (not rename it)
        assert result["id"] == "existing"

    def test_list_agents(self, tmp_path):
        store = GraphStore(str(tmp_path / "list_agents_test"))
        store.get_or_create_agent("a1", name="Claude")
        store.get_or_create_agent("a2", name="Codex")
        agents = store.list_agents()
        assert len(agents) == 2
        ids = {a["id"] for a in agents}
        assert "a1" in ids
        assert "a2" in ids


# ── Agent tracking in Fact/Rule ───────────────────────────────────────────────

class TestAgentTracking:
    def test_fact_has_agent_id(self, tmp_path):
        store = GraphStore(str(tmp_path / "fact_agent_test"))
        fact = Fact(text="Test fact", agent_id="agent-claude")
        store.add_fact(fact)
        rows = store.query(f"MATCH (f:Fact {{id:'{fact.id}'}}) RETURN f.agent_id")
        assert rows[0][0] == "agent-claude"

    def test_rule_has_agent_id(self, tmp_path):
        store = GraphStore(str(tmp_path / "rule_agent_test"))
        rule = Rule(text="Always test", rule_type="instruction", agent_id="agent-gemini")
        store.add_rule(rule)
        rows = store.query(f"MATCH (r:Rule {{id:'{rule.id}'}}) RETURN r.agent_id")
        assert rows[0][0] == "agent-gemini"

    def test_default_agent_id(self, tmp_path):
        store = GraphStore(str(tmp_path / "default_agent_test"))
        fact = Fact(text="Default agent fact")
        store.add_fact(fact)
        rows = store.query(f"MATCH (f:Fact {{id:'{fact.id}'}}) RETURN f.agent_id")
        assert rows[0][0] == "default"

    def test_created_by_edge(self, tmp_path):
        store = GraphStore(str(tmp_path / "created_by_test"))
        store.get_or_create_agent("agent-claude", name="Claude")
        fact = Fact(text="Claude created this", agent_id="agent-claude")
        store.add_fact(fact)
        store.add_created_by(fact.id, "agent-claude")
        rows = store.query(
            f"MATCH (f:Fact {{id:'{fact.id}'}})-[:CREATED_BY]->(a:Agent) "
            f"RETURN a.id, a.name"
        )
        assert rows
        assert rows[0][0] == "agent-claude"
        assert rows[0][1] == "Claude"

    def test_agent_stats(self, tmp_path):
        store = GraphStore(str(tmp_path / "agent_stats_test"))
        store.get_or_create_agent("stats-agent", name="StatsBot")
        for i in range(3):
            store.add_fact(Fact(text=f"Fact {i}", agent_id="stats-agent"))
        store.add_rule(Rule(text="Rule 0", agent_id="stats-agent"))
        stats = store.get_agent_stats("stats-agent")
        assert stats["agent_id"] == "stats-agent"
        assert stats["facts"] == 3
        assert stats["rules"] == 1

    def test_get_facts_by_agent(self, tmp_path):
        store = GraphStore(str(tmp_path / "by_agent_test"))
        store.get_or_create_agent("a1")
        store.get_or_create_agent("a2")
        store.add_fact(Fact(text="A1 fact", agent_id="a1"))
        store.add_fact(Fact(text="A2 fact", agent_id="a2"))
        rows = store.query("MATCH (f:Fact {agent_id:'a1'}) RETURN f.text")
        assert len(rows) == 1
        assert rows[0][0] == "A1 fact"


# ── LorienMemory multi-agent API ──────────────────────────────────────────────

class TestLorienMemoryMultiAgent:
    def test_register_agent(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "reg_agent"), enable_vectors=False)
        result = mem.register_agent("claude-agent", name="Claude Sonnet")
        assert result["id"] == "claude-agent"

    def test_get_agents_empty(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "get_agents_empty"), enable_vectors=False)
        assert mem.get_agents() == []

    def test_get_agents_after_register(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "get_agents"), enable_vectors=False)
        mem.register_agent("a1", name="Claude")
        mem.register_agent("a2", name="Codex")
        agents = mem.get_agents()
        assert len(agents) == 2

    def test_get_agent_stats(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "agent_stats_mem"), enable_vectors=False)
        mem.register_agent("bot1", name="Bot One")
        mem.store.add_fact(Fact(text="Bot fact", agent_id="bot1"))
        stats = mem.get_agent_stats("bot1")
        assert stats["facts"] >= 1

    def test_get_agent_stats_unknown(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "agent_stats_unknown"), enable_vectors=False)
        stats = mem.get_agent_stats("nobody")
        assert stats["facts"] == 0
        assert stats["rules"] == 0


# ── WriteQueue ────────────────────────────────────────────────────────────────

class TestWriteQueue:
    def test_basic_submit(self):
        results = []
        with WriteQueue() as wq:
            future = wq.submit(lambda: results.append(1) or 42)
            assert future.result(timeout=2.0) == 42
        assert results == [1]

    def test_fifo_ordering(self):
        order = []
        with WriteQueue() as wq:
            futures = [wq.submit(lambda i=i: order.append(i)) for i in range(5)]
            for f in futures:
                f.result(timeout=2.0)
        assert order == [0, 1, 2, 3, 4]

    def test_submit_sync(self):
        with WriteQueue() as wq:
            result = wq.submit_sync(lambda: 99)
        assert result == 99

    def test_exception_propagation(self):
        with WriteQueue() as wq:
            future = wq.submit(lambda: 1 / 0)
            with pytest.raises(ZeroDivisionError):
                future.result(timeout=2.0)

    def test_concurrent_submissions(self):
        counter = [0]
        lock = threading.Lock()

        def increment():
            with lock:
                counter[0] += 1

        with WriteQueue() as wq:
            futures = [wq.submit(increment) for _ in range(20)]
            for f in futures:
                f.result(timeout=5.0)

        assert counter[0] == 20

    def test_shutdown_prevents_new_submissions(self):
        wq = WriteQueue()
        wq.shutdown()
        with pytest.raises(RuntimeError, match="shut down"):
            wq.submit(lambda: None)

    def test_queue_size_tracking(self):
        # Just verify queue_size() is callable and returns int
        with WriteQueue() as wq:
            assert isinstance(wq.queue_size(), int)
