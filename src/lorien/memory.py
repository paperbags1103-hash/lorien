"""LorienMemory — Mem0-compatible real-time conversation memory interface."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .ingest import LorienIngester
from .query import KnowledgeGraph
from .schema import GraphStore

# ─── Conversation extraction prompt ──────────────────────────────────────────
CONV_SYSTEM_PROMPT = """You are a knowledge graph extraction assistant for an AI agent.
Extract structured knowledge from the conversation below.

Output ONLY valid JSON matching this schema:
{
  "entities": [{"name": str, "entity_type": str, "aliases": [str], "description": str, "confidence": float}],
  "facts": [{"text": str, "subject": str, "predicate": str, "object": str|null, "fact_type": str, "confidence": float, "negated": bool}],
  "rules": [{"text": str, "subject": str, "rule_type": str, "priority": int, "confidence": float}],
  "relations": [{"source": str, "target": str, "rel_type": str, "confidence": float}]
}

entity_type: person, org, project, tool, concept, place
fact_type: statement, preference, observation, biographical, technical
rule_type: prohibition, fixed, preference, instruction
priority: 0-100
rel_type: RELATED_TO, CAUSED, CONTRADICTS

Focus on:
- Personal preferences, habits, opinions
- Plans and intentions
- Important facts about people, projects, tools
- Hard constraints or rules stated by the user

Be conservative. Low confidence is better than wrong data.
Ignore pleasantries and filler."""

CONV_USER_PROMPT = """Extract knowledge from this conversation for user: {user_id}

{conversation}

Return ONLY JSON."""

# ─── LorienMemory ─────────────────────────────────────────────────────────────

class LorienMemory:
    """Mem0-compatible real-time conversation memory backed by lorien graph.

    Usage:
        mem = LorienMemory(model="haiku")          # auto-uses OpenClaw gateway
        mem.add(messages, user_id="아부지")
        results = mem.search("좋아하는 프로젝트", user_id="아부지")
        all_facts = mem.get_all(user_id="아부지")
    """

    def __init__(
        self,
        db_path: str = "~/.lorien/db",
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        enable_vectors: bool = True,
    ) -> None:
        self.store = GraphStore(db_path=db_path)
        self.ingester = LorienIngester(
            self.store,
            llm_model=model,
            api_key=api_key,
            base_url=base_url,
            enable_vectors=enable_vectors,
        )
        self.graph = KnowledgeGraph(self.store)
        self.vectors = self.ingester.vectors  # None if sentence-transformers not installed or disabled

    def add(
        self,
        messages: list[dict[str, str]],
        user_id: str = "user",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        """Extract and store knowledge from a conversation.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."}
            user_id: Entity name to associate this conversation with
            metadata: Optional extra metadata (unused, for API compatibility)

        Returns:
            {"entities": N, "facts": N, "rules": N, "edges": N}
        """
        # Format conversation text
        lines = []
        for m in messages:
            role = m.get("role", "user").capitalize()
            content = m.get("content", "").strip()
            if content and m.get("role") != "system":
                lines.append(f"{role}: {content}")
        if not lines:
            return {"entities": 0, "facts": 0, "rules": 0, "edges": 0}

        conversation_text = "\n".join(lines)
        source = f"conversation:{user_id}:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"

        # Use conversation-specific prompts for LLM path; keyword fallback uses plain text
        if self.ingester.llm_model and self.ingester.api_key:
            result = self._llm_ingest_conversation(
                conversation_text, user_id=user_id, source=source
            )
        else:
            # Keyword fallback: ingest just the conversation text
            result = self.ingester.ingest_text(conversation_text, source=source)

        return {
            "entities": result.entities_added,
            "facts": result.facts_added,
            "rules": result.rules_added,
            "edges": result.edges_added,
        }

    def _llm_ingest_conversation(
        self, conversation_text: str, user_id: str, source: str
    ):
        """Use conversation-specific LLM prompt to extract from conversation."""
        import json
        import re
        import urllib.request

        prompt = CONV_USER_PROMPT.format(
            user_id=user_id, conversation=conversation_text
        )
        ingester = self.ingester

        if ingester._use_openclaw or not (
            ingester.llm_model and ingester.llm_model.startswith("claude")
        ):
            # OpenAI-compatible (OpenClaw gateway or OpenAI)
            payload = json.dumps({
                "model": ingester.llm_model,
                "messages": [
                    {"role": "system", "content": CONV_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
            }).encode()
            req = urllib.request.Request(
                f"{ingester.base_url}/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {ingester.api_key}",
                    "Content-Type": "application/json",
                },
            )
        else:
            # Anthropic Messages API
            combined = CONV_SYSTEM_PROMPT + "\n\n" + prompt
            payload = json.dumps({
                "model": ingester.llm_model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": combined}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "x-api-key": ingester.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )

        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = json.loads(response.read())
            if "choices" in raw:
                content = raw["choices"][0]["message"]["content"]
            else:
                content = raw["content"][0]["text"]
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                triples = ingester._parse_llm_output(json.loads(json_match.group()))
                return ingester._store_triples(triples, source)
        except Exception:
            pass

        # Fallback to keyword extraction on LLM failure
        return ingester.ingest_text(conversation_text, source=source)

    def search(
        self,
        query: str,
        user_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search memories — vector (semantic) when available, keyword fallback.

        Args:
            query: Search string
            user_id: If given, filter to this entity's facts/rules
            limit: Max results

        Returns:
            List of {"id", "memory", "score", "type": "fact"|"rule", ...}
        """
        # Build entity fact/rule id sets for filtering (when user_id given)
        allowed_ids: set[str] | None = None
        if user_id:
            entity = self.graph.get_entity(user_id)
            if entity:
                ctx = self.graph.get_entity_context(entity["id"])
                allowed_ids = {f["id"] for f in ctx["facts"]} | {r["id"] for r in ctx["rules"]}
            else:
                return []

        # ── Vector search path ────────────────────────────────────────────
        if self.vectors:
            raw = self.vectors.search(query, top_k=limit * 3)
            results = []
            for r in raw:
                nid = r["id"]
                if allowed_ids is not None and nid not in allowed_ids:
                    continue
                # Enrich with Kuzu data
                ntype = r["node_type"]
                if ntype == "Rule":
                    rows = self.store.query(
                        f"MATCH (n:Rule {{id:'{nid}'}}) RETURN n.priority"
                    )
                    priority = rows[0][0] if rows else 50
                    results.append({
                        "id": nid, "memory": r["text"],
                        "score": r["score"], "type": "rule",
                        "priority": priority,
                        **({"user_id": user_id} if user_id else {}),
                    })
                else:
                    results.append({
                        "id": nid, "memory": r["text"],
                        "score": r["score"], "type": "fact",
                        **({"user_id": user_id} if user_id else {}),
                    })
                if len(results) >= limit:
                    break
            return results

        # ── Keyword fallback ─────────────────────────────────────────────
        results = []
        q = query.lower()

        if user_id:
            entity = self.graph.get_entity(user_id)
            if entity:
                ctx = self.graph.get_entity_context(entity["id"])
                for f in ctx["facts"]:
                    if q in f["text"].lower():
                        results.append({
                            "id": f["id"], "memory": f["text"],
                            "score": f["confidence"], "type": "fact",
                            "user_id": user_id,
                        })
                for r in ctx["rules"]:
                    if q in r["text"].lower():
                        results.append({
                            "id": r["id"], "memory": r["text"],
                            "score": r["confidence"], "type": "rule",
                            "priority": r["priority"], "user_id": user_id,
                        })
        else:
            for fid, text, conf in self.store.query(
                f"MATCH (f:Fact) WHERE f.status = 'active' "
                f"RETURN f.id, f.text, f.confidence LIMIT {int(limit) * 5}"
            ):
                if q in text.lower():
                    results.append({"id": fid, "memory": text, "score": conf, "type": "fact"})
            for rid, text, priority in self.store.query(
                f"MATCH (r:Rule) WHERE r.status = 'active' "
                f"RETURN r.id, r.text, r.priority LIMIT {int(limit) * 2}"
            ):
                if q in text.lower():
                    results.append({"id": rid, "memory": text, "score": 1.0,
                                    "type": "rule", "priority": priority})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def get_all(
        self,
        user_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return all memories for a user (or global).

        Returns:
            List of {"id", "memory", "type", "score", ...}
        """
        results = []

        if user_id:
            entity = self.graph.get_entity(user_id)
            if entity:
                ctx = self.graph.get_entity_context(entity["id"])
                for f in ctx["facts"]:
                    results.append({
                        "id": f["id"],
                        "memory": f["text"],
                        "score": f["confidence"],
                        "type": "fact",
                        "user_id": user_id,
                        "created_at": f.get("created_at", ""),
                    })
                for r in ctx["rules"]:
                    results.append({
                        "id": r["id"],
                        "memory": r["text"],
                        "score": 1.0,
                        "type": "rule",
                        "priority": r["priority"],
                        "user_id": user_id,
                    })
        else:
            fact_rows = self.store.query(
                f"MATCH (f:Fact) WHERE f.status = 'active' "
                f"RETURN f.id, f.text, f.confidence, f.created_at "
                f"ORDER BY f.created_at DESC LIMIT {int(limit)}"
            )
            for fid, text, conf, created in fact_rows:
                results.append({
                    "id": fid, "memory": text,
                    "score": conf, "type": "fact",
                    "created_at": created,
                })

        return results[:limit]

    def delete(self, memory_id: str) -> bool:
        """Soft-delete a memory (Fact or Rule) by id."""
        safe_id = self.store._q(memory_id)
        for table in ("Fact", "Rule"):  # whitelist — no user input reaches table name
            self.store.conn.execute(
                f"MATCH (n:{table} {{id: {safe_id}}}) SET n.status = 'deleted'"
            )
        return True

    def get_entity_rules(self, entity_name: str) -> list[dict]:
        """Return all hard rules for an entity — lorien-exclusive feature."""
        entity = self.graph.get_entity(entity_name)
        if not entity:
            return []
        return self.graph.get_active_rules(entity["id"])

    # ── v0.3 Multi-agent API ───────────────────────────────────────────────────

    def register_agent(self, agent_id: str, name: str | None = None, agent_type: str = "llm") -> dict:
        """Register (or refresh) an agent in the knowledge graph.

        Safe to call multiple times — returns existing agent if already present.
        """
        return self.store.get_or_create_agent(agent_id, name=name, agent_type=agent_type)

    def get_agents(self) -> list[dict]:
        """Return all registered agents, ordered by last activity."""
        return self.store.list_agents()

    def get_agent_stats(self, agent_id: str) -> dict:
        """Return stats for a specific agent: fact/rule counts, last active, etc."""
        return self.store.get_agent_stats(agent_id)

    def add_with_agent(
        self,
        messages: list[dict],
        user_id: str,
        agent_id: str = "default",
        agent_name: str | None = None,
        agent_type: str = "llm",
    ) -> dict:
        """Add conversation with explicit agent attribution.

        Like add(), but tags all extracted Facts with agent_id and creates
        CREATED_BY edges to the Agent node.

        Returns:
            Same structure as add(), with agent_id included.
        """
        # Ensure agent exists
        self.store.get_or_create_agent(agent_id, name=agent_name, agent_type=agent_type)

        result = self.add(messages, user_id)

        # Tag all newly-created facts with agent_id + create CREATED_BY edges
        fact_ids = [f["id"] for f in result.get("facts", [])]
        for fid in fact_ids:
            try:
                self.store.conn.execute(
                    f"MATCH (f:Fact {{id:{self.store._q(fid)}}}) "
                    f"SET f.agent_id = {self.store._q(agent_id)}"
                )
                self.store.add_created_by(fid, agent_id)
            except Exception:
                pass

        result["agent_id"] = agent_id
        return result

    def get_contradictions(self) -> list[dict]:
        """Return detected contradictions — lorien-exclusive feature."""
        return self.graph.find_contradictions()

    # ── v0.3 Temporal API ──────────────────────────────────────────────────────

    def confirm(self, fact_ids: list[str]) -> int:
        """Mark facts as recently confirmed — resets freshness to 1.0.

        Use when you've verified stored facts are still accurate.

        Returns:
            Number of facts updated.
        """
        updated = 0
        for fid in fact_ids:
            try:
                self.store.confirm_fact(fid)
                updated += 1
            except Exception:
                pass
        return updated

    def get_fact_history(self, entity_name: str, predicate: str | None = None) -> list[dict]:
        """Return the version history of facts for an entity.

        Shows how knowledge has evolved over time (SUPERSEDES chain).

        Returns:
            List of facts ordered by created_at, newest first.
            Each dict includes freshness_score.
        """
        from .temporal import freshness_score as _freshness

        entity = self.graph.get_entity(entity_name)
        if not entity:
            return []

        pred_clause = ""
        if predicate:
            safe_pred = predicate.replace("'", "\\'")
            pred_clause = f"AND f.predicate CONTAINS '{safe_pred}' "

        rows = self.store.query(
            f"MATCH (f:Fact)-[:ABOUT]->(e:Entity {{id:'{entity['id']}'}}) "
            f"WHERE f.subject_id = '{entity['id']}' {pred_clause}"
            f"RETURN f.id, f.text, f.status, f.created_at, f.last_confirmed, "
            f"f.confidence, f.version "
            f"ORDER BY f.created_at DESC LIMIT 50"
        )

        results = []
        for row in rows:
            fid, text, status, created, confirmed, conf, version = row
            results.append({
                "id": fid,
                "text": text,
                "status": status,
                "created_at": created or "",
                "last_confirmed": confirmed or "",
                "confidence": conf or 0.0,
                "version": version or 1,
                "freshness_score": _freshness(confirmed or created or ""),
            })
        return results

    def cleanup(
        self,
        max_age_days: int = 90,
        min_confidence: float = 0.3,
    ) -> dict:
        """Expire stale facts that haven't been confirmed recently.

        A fact is expired when:
        - Age since last_confirmed > max_age_days AND
        - confidence < min_confidence

        Returns:
            {"expired": int} — number of facts expired.
        """
        expired = self.store.expire_stale_facts(
            max_age_days=max_age_days,
            min_confidence=min_confidence,
        )
        return {"expired": expired}

    # ── v0.3 Decision Archive API ──────────────────────────────────────────────

    def add_decision(
        self,
        text: str,
        decision_type: str = "action",
        context: str = "",
        agent_id: str = "default",
        supporting_fact_ids: list[str] | None = None,
        opposing_fact_ids: list[str] | None = None,
        rule_ids: list[str] | None = None,
        confidence: float = 1.0,
    ) -> str:
        """Record a decision with its supporting evidence.

        Args:
            text: What was decided.
            decision_type: "action" | "judgment" | "preference" | "plan"
            context: Situation summary at decision time.
            agent_id: Which agent made this decision.
            supporting_fact_ids: Fact IDs that support this decision.
            opposing_fact_ids: Fact IDs considered but overridden.
            rule_ids: Rule IDs that were applied.
            confidence: Decision confidence 0.0-1.0.

        Returns:
            decision_id
        """
        from .models import Decision

        # Ensure agent exists
        self.store.get_or_create_agent(agent_id)

        decision = Decision(
            text=text,
            decision_type=decision_type,
            context=context,
            agent_id=agent_id,
            confidence=confidence,
        )
        self.store.add_decision(decision)

        # DECIDED_BY edge
        try:
            self.store.add_decided_by(decision.id, agent_id)
        except Exception:
            pass

        # BASED_ON edges
        for fid in (supporting_fact_ids or []):
            try:
                self.store.add_based_on(decision.id, fid, role="supporting")
            except Exception:
                pass
        for fid in (opposing_fact_ids or []):
            try:
                self.store.add_based_on(decision.id, fid, role="opposing")
            except Exception:
                pass

        # APPLIED_RULE edges
        for rid in (rule_ids or []):
            try:
                self.store.add_applied_rule(decision.id, rid)
            except Exception:
                pass

        return decision.id

    def why(self, decision_id_or_query: str) -> dict:
        """Answer 'why was this decision made?' — returns causal chain.

        Accepts either a decision_id directly or a text query to find
        the most relevant decision.

        Returns:
            {
                "decision": {...},
                "supporting_facts": [...],
                "opposing_facts": [...],
                "applied_rules": [...],
            }
        """
        # Try direct ID lookup first
        chain = self.store.get_decision_chain(decision_id_or_query)
        if not chain:
            # Fall back to text search
            results = self.store.search_decisions(decision_id_or_query, limit=1)
            if results:
                chain = self.store.get_decision_chain(results[0]["id"])

        if not chain:
            return {"error": f"No decision found for: {decision_id_or_query}"}

        return {
            "decision": {
                "id": chain["id"],
                "text": chain["text"],
                "decision_type": chain["decision_type"],
                "context": chain["context"],
                "agent_id": chain["agent_id"],
                "confidence": chain["confidence"],
                "status": chain["status"],
                "created_at": chain["created_at"],
            },
            "supporting_facts": chain["supporting_facts"],
            "opposing_facts": chain["opposing_facts"],
            "applied_rules": chain["applied_rules"],
        }

    def search_decisions(self, query: str, limit: int = 10) -> list[dict]:
        """Search decisions by text or context."""
        return self.store.search_decisions(query, limit=limit)

    def revoke_decision(self, decision_id: str) -> bool:
        """Mark a decision as revoked (no longer active)."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        try:
            self.store.conn.execute(
                f"MATCH (d:Decision {{id:{self.store._q(decision_id)}}}) "
                f"SET d.status = 'revoked', d.updated_at = {self.store._q(now)}"
            )
            return True
        except Exception:
            return False

    def freshness(self, fact_id: str) -> float:
        """Get the freshness score (0.0–1.0) for a specific fact."""
        from .temporal import freshness_score as _freshness

        rows = self.store.query(
            f"MATCH (f:Fact {{id:'{fact_id}'}}) "
            f"RETURN f.last_confirmed, f.created_at LIMIT 1"
        )
        if not rows:
            return 0.0
        confirmed, created = rows[0]
        return _freshness(confirmed or created or "")
