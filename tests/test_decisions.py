"""Tests for Decision archive (lorien v0.3 Phase 3)."""
from __future__ import annotations

import pytest

from lorien.schema import GraphStore
from lorien.models import Decision, Fact, Rule, Agent
from lorien.memory import LorienMemory


# ── GraphStore Decision node ──────────────────────────────────────────────────

class TestDecisionNode:
    def test_add_decision(self, tmp_path):
        store = GraphStore(str(tmp_path / "dec_test"))
        dec = Decision(
            text="Use REST API over GraphQL",
            decision_type="judgment",
            context="GraphQL is overkill for this simple CRUD app",
            agent_id="claude",
        )
        store.add_decision(dec)
        rows = store.query(
            f"MATCH (d:Decision {{id:'{dec.id}'}}) "
            f"RETURN d.text, d.decision_type, d.status, d.agent_id"
        )
        assert rows
        text, dtype, status, agent = rows[0]
        assert text == "Use REST API over GraphQL"
        assert dtype == "judgment"
        assert status == "active"
        assert agent == "claude"

    def test_decision_default_fields(self, tmp_path):
        store = GraphStore(str(tmp_path / "dec_default"))
        dec = Decision(text="Ship it")
        store.add_decision(dec)
        rows = store.query(
            f"MATCH (d:Decision {{id:'{dec.id}'}}) "
            f"RETURN d.decision_type, d.status, d.confidence, d.agent_id"
        )
        assert rows
        dtype, status, conf, agent = rows[0]
        assert dtype == "action"
        assert status == "active"
        assert conf == 1.0
        assert agent == "default"


# ── Decision edges ────────────────────────────────────────────────────────────

class TestDecisionEdges:
    def test_based_on_supporting(self, tmp_path):
        store = GraphStore(str(tmp_path / "based_on_test"))
        fact = Fact(text="REST is simpler to implement")
        dec = Decision(text="Use REST")
        store.add_fact(fact)
        store.add_decision(dec)
        store.add_based_on(dec.id, fact.id, role="supporting")
        rows = store.query(
            f"MATCH (d:Decision {{id:'{dec.id}'}})"
            f"-[r:BASED_ON]->(f:Fact) RETURN f.text, r.role"
        )
        assert rows
        assert rows[0][0] == "REST is simpler to implement"
        assert rows[0][1] == "supporting"

    def test_based_on_opposing(self, tmp_path):
        store = GraphStore(str(tmp_path / "opposing_test"))
        fact = Fact(text="GraphQL offers flexible queries")
        dec = Decision(text="Use REST anyway")
        store.add_fact(fact)
        store.add_decision(dec)
        store.add_based_on(dec.id, fact.id, role="opposing")
        rows = store.query(
            f"MATCH (d:Decision {{id:'{dec.id}'}})"
            f"-[r:BASED_ON]->(f:Fact) RETURN r.role"
        )
        assert rows[0][0] == "opposing"

    def test_applied_rule(self, tmp_path):
        store = GraphStore(str(tmp_path / "applied_rule_test"))
        rule = Rule(text="Keep APIs simple", rule_type="preference", priority=70)
        dec = Decision(text="Use REST")
        store.add_rule(rule)
        store.add_decision(dec)
        store.add_applied_rule(dec.id, rule.id, role="primary")
        rows = store.query(
            f"MATCH (d:Decision {{id:'{dec.id}'}})"
            f"-[r:APPLIED_RULE]->(rl:Rule) RETURN rl.text, r.role"
        )
        assert rows
        assert rows[0][0] == "Keep APIs simple"
        assert rows[0][1] == "primary"

    def test_decided_by(self, tmp_path):
        store = GraphStore(str(tmp_path / "decided_by_test"))
        store.get_or_create_agent("claude-3", name="Claude")
        dec = Decision(text="Use Python", agent_id="claude-3")
        store.add_decision(dec)
        store.add_decided_by(dec.id, "claude-3")
        rows = store.query(
            f"MATCH (d:Decision {{id:'{dec.id}'}})-[:DECIDED_BY]->(a:Agent) "
            f"RETURN a.name"
        )
        assert rows
        assert rows[0][0] == "Claude"

    def test_supersede_decision(self, tmp_path):
        store = GraphStore(str(tmp_path / "supersede_dec_test"))
        old = Decision(text="Use Python 3.11")
        new = Decision(text="Use Python 3.12")
        store.add_decision(old)
        store.add_decision(new)
        store.supersede_decision(new.id, old.id, reason="version_upgrade")
        # Old should be superseded
        rows = store.query(f"MATCH (d:Decision {{id:'{old.id}'}}) RETURN d.status")
        assert rows[0][0] == "superseded"
        # SUPERSEDES_D edge exists
        edge = store.query(
            f"MATCH (a:Decision)-[:SUPERSEDES_D]->(b:Decision) "
            f"WHERE a.id = '{new.id}' RETURN b.id"
        )
        assert edge[0][0] == old.id


# ── get_decision_chain ────────────────────────────────────────────────────────

class TestDecisionChain:
    def test_get_full_chain(self, tmp_path):
        store = GraphStore(str(tmp_path / "chain_test"))
        fact_s = Fact(text="Python has great libraries")
        fact_o = Fact(text="Go is faster")
        rule = Rule(text="Prefer developer velocity", rule_type="preference", priority=60)
        dec = Decision(
            text="Use Python for this project",
            decision_type="judgment",
            context="Building a data pipeline",
        )
        store.add_fact(fact_s)
        store.add_fact(fact_o)
        store.add_rule(rule)
        store.add_decision(dec)
        store.add_based_on(dec.id, fact_s.id, role="supporting")
        store.add_based_on(dec.id, fact_o.id, role="opposing")
        store.add_applied_rule(dec.id, rule.id, role="primary")

        chain = store.get_decision_chain(dec.id)
        assert chain["text"] == "Use Python for this project"
        assert chain["decision_type"] == "judgment"
        assert len(chain["supporting_facts"]) == 1
        assert len(chain["opposing_facts"]) == 1
        assert len(chain["applied_rules"]) == 1
        assert chain["supporting_facts"][0]["text"] == "Python has great libraries"
        assert chain["opposing_facts"][0]["text"] == "Go is faster"
        assert chain["applied_rules"][0]["text"] == "Prefer developer velocity"

    def test_get_chain_nonexistent(self, tmp_path):
        store = GraphStore(str(tmp_path / "chain_none"))
        chain = store.get_decision_chain("nonexistent-id")
        assert chain == {}

    def test_search_decisions(self, tmp_path):
        store = GraphStore(str(tmp_path / "search_dec_test"))
        store.add_decision(Decision(text="Use PostgreSQL for persistence"))
        store.add_decision(Decision(text="Use Redis for caching"))
        store.add_decision(Decision(text="Deploy on AWS"))
        results = store.search_decisions("PostgreSQL")
        assert len(results) >= 1
        assert any("PostgreSQL" in r["text"] for r in results)

    def test_search_decisions_by_context(self, tmp_path):
        store = GraphStore(str(tmp_path / "search_ctx_test"))
        store.add_decision(Decision(
            text="Use microservices",
            context="High team scale, independent deployments needed",
        ))
        results = store.search_decisions("microservices")
        assert len(results) == 1
        assert results[0]["text"] == "Use microservices"


# ── LorienMemory Decision API ─────────────────────────────────────────────────

class TestLorienMemoryDecisions:
    def test_add_decision_returns_id(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_dec"), enable_vectors=False)
        did = mem.add_decision("Use REST API", decision_type="judgment")
        assert isinstance(did, str)
        assert len(did) > 0

    def test_add_decision_with_supporting_facts(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_dec_facts"), enable_vectors=False)
        fact = Fact(text="REST is well understood")
        mem.store.add_fact(fact)
        did = mem.add_decision(
            "Choose REST",
            supporting_fact_ids=[fact.id],
        )
        chain = mem.store.get_decision_chain(did)
        assert len(chain["supporting_facts"]) == 1
        assert chain["supporting_facts"][0]["id"] == fact.id

    def test_add_decision_with_rules(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_dec_rules"), enable_vectors=False)
        rule = Rule(text="Keep it simple", rule_type="preference", priority=80)
        mem.store.add_rule(rule)
        did = mem.add_decision("Use simplest approach", rule_ids=[rule.id])
        chain = mem.store.get_decision_chain(did)
        assert len(chain["applied_rules"]) == 1

    def test_why_by_id(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_why"), enable_vectors=False)
        did = mem.add_decision(
            text="Adopt TypeScript",
            context="Type safety prevents runtime bugs",
            decision_type="judgment",
        )
        result = mem.why(did)
        assert "decision" in result
        assert result["decision"]["text"] == "Adopt TypeScript"
        assert "supporting_facts" in result
        assert "applied_rules" in result

    def test_why_by_text_query(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_why_text"), enable_vectors=False)
        mem.add_decision("Migrate to Kubernetes for container orchestration")
        result = mem.why("Kubernetes")
        assert "decision" in result
        assert "Kubernetes" in result["decision"]["text"]

    def test_why_not_found(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_why_none"), enable_vectors=False)
        result = mem.why("totally nonexistent query xyz")
        assert "error" in result

    def test_search_decisions(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_search_dec"), enable_vectors=False)
        mem.add_decision("Use PostgreSQL")
        mem.add_decision("Use Redis")
        results = mem.search_decisions("PostgreSQL")
        assert len(results) >= 1
        assert any("PostgreSQL" in r["text"] for r in results)

    def test_revoke_decision(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_revoke"), enable_vectors=False)
        did = mem.add_decision("Temporary decision")
        mem.revoke_decision(did)
        chain = mem.store.get_decision_chain(did)
        assert chain["status"] == "revoked"

    def test_add_decision_creates_decided_by_edge(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_dec_agent"), enable_vectors=False)
        mem.register_agent("gpt4", name="GPT-4")
        did = mem.add_decision("Use GPT-4 for summarization", agent_id="gpt4")
        rows = mem.store.query(
            f"MATCH (d:Decision {{id:'{did}'}})-[:DECIDED_BY]->(a:Agent) RETURN a.id"
        )
        assert rows
        assert rows[0][0] == "gpt4"

    def test_opposing_facts_in_chain(self, tmp_path):
        mem = LorienMemory(db_path=str(tmp_path / "mem_opposing"), enable_vectors=False)
        pro = Fact(text="Fast dev velocity")
        con = Fact(text="Python slower than Go at runtime")
        mem.store.add_fact(pro)
        mem.store.add_fact(con)
        did = mem.add_decision(
            "Choose Python despite runtime cost",
            supporting_fact_ids=[pro.id],
            opposing_fact_ids=[con.id],
        )
        result = mem.why(did)
        assert len(result["supporting_facts"]) == 1
        assert len(result["opposing_facts"]) == 1
