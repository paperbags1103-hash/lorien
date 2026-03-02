"""KnowledgeGraph: high-level read interface over GraphStore."""

from __future__ import annotations

from datetime import datetime, timezone

from .schema import GraphStore


class KnowledgeGraph:
    """Read-oriented facade with semantic query methods over GraphStore.

    All user-supplied strings are sanitised via _safe() to prevent Cypher injection.
    """

    def __init__(self, store: GraphStore) -> None:
        self.store = store

    @staticmethod
    def _safe(s: str) -> str:
        """Escape a string for safe embedding in a Cypher single-quoted literal."""
        s = s.replace("\\", "\\\\")
        s = s.replace("'", "\\'")
        return s

    def get_entity(self, name: str) -> dict | None:
        """Return the first active entity matching name (case-insensitive)."""
        safe_name = self._safe(name)
        rows = self.store.query(
            f"MATCH (e:Entity) WHERE lower(e.name) = lower('{safe_name}') "
            f"AND e.status = 'active' RETURN e.id, e.name, e.entity_type, e.canonical_key LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return {"id": r[0], "name": r[1], "entity_type": r[2], "canonical_key": r[3]}

    def find_entity_by_canonical_key(self, canonical_key: str) -> dict | None:
        safe_key = self._safe(canonical_key)
        rows = self.store.query(
            f"MATCH (e:Entity) WHERE e.canonical_key = '{safe_key}' "
            f"AND e.status = 'active' RETURN e.id, e.name, e.entity_type, e.canonical_key LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return {"id": r[0], "name": r[1], "entity_type": r[2], "canonical_key": r[3]}

    def get_entity_context(self, entity_id: str) -> dict:
        """Return all active facts and rules linked to entity_id."""
        safe_id = self._safe(entity_id)
        facts = self.store.query(
            f"MATCH (f:Fact)-[:ABOUT]->(e:Entity) WHERE e.id = '{safe_id}' "
            f"AND f.status = 'active' RETURN f.id, f.text, f.confidence, f.created_at "
            f"ORDER BY f.created_at DESC"
        )
        rules = self.store.query(
            f"MATCH (e:Entity)-[:HAS_RULE]->(r:Rule) WHERE e.id = '{safe_id}' "
            f"AND r.status = 'active' RETURN r.id, r.text, r.rule_type, r.priority "
            f"ORDER BY r.priority DESC"
        )
        return {
            "entity_id": entity_id,
            "facts": [{"id": r[0], "text": r[1], "confidence": r[2], "created_at": r[3]} for r in facts],
            "rules": [{"id": r[0], "text": r[1], "rule_type": r[2], "priority": r[3]} for r in rules],
        }

    def find_contradictions(self) -> list[dict]:
        """Return all active CONTRADICTS edges."""
        rows = self.store.query(
            "MATCH (a:Fact)-[:CONTRADICTS]->(b:Fact) "
            "WHERE a.status = 'active' AND b.status = 'active' "
            "RETURN a.id, a.text, b.id, b.text, a.created_at, b.created_at "
            "ORDER BY a.created_at DESC"
        )
        return [
            {"fact_a": {"id": r[0], "text": r[1], "created_at": r[4]},
             "fact_b": {"id": r[2], "text": r[3], "created_at": r[5]}}
            for r in rows
        ]

    def get_causal_chain(self, fact_id: str, depth: int = 3) -> list[dict]:
        """Follow CAUSED edges from fact_id up to depth hops."""
        safe_id = self._safe(fact_id)
        rows = self.store.query(
            f"MATCH (s:Fact)-[:CAUSED*1..{int(depth)}]->(e:Fact) "
            f"WHERE s.id = '{safe_id}' AND e.status = 'active' "
            f"RETURN e.id, e.text, e.confidence"
        )
        return [{"id": r[0], "text": r[1], "confidence": r[2]} for r in rows]

    def get_recent_facts(self, limit: int = 20) -> list[dict]:
        """Return most recently created active facts."""
        rows = self.store.query(
            f"MATCH (f:Fact) WHERE f.status = 'active' "
            f"RETURN f.id, f.text, f.confidence, f.source, f.created_at "
            f"ORDER BY f.created_at DESC LIMIT {int(limit)}"
        )
        return [
            {"id": r[0], "text": r[1], "confidence": r[2], "source": r[3], "created_at": r[4]}
            for r in rows
        ]

    def get_active_rules(self, entity_id: str | None = None) -> list[dict]:
        """Return active rules, optionally scoped to a single entity."""
        if entity_id:
            safe_id = self._safe(entity_id)
            rows = self.store.query(
                f"MATCH (e:Entity)-[:HAS_RULE]->(r:Rule) WHERE e.id = '{safe_id}' "
                f"AND r.status = 'active' RETURN r.id, r.text, r.rule_type, r.priority, r.confidence "
                f"ORDER BY r.priority DESC"
            )
        else:
            rows = self.store.query(
                "MATCH (r:Rule) WHERE r.status = 'active' "
                "RETURN r.id, r.text, r.rule_type, r.priority, r.confidence "
                "ORDER BY r.priority DESC, r.created_at DESC"
            )
        return [
            {"id": r[0], "text": r[1], "rule_type": r[2], "priority": r[3], "confidence": r[4]}
            for r in rows
        ]

    def export_to_memory_md(self, entity_name: str | None = None) -> str:
        """Render graph as MEMORY.md-style markdown. Filter by entity_name if given."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines: list[str] = [f"# lorien Export ({now})\n"]

        if entity_name:
            entity = self.get_entity(entity_name)
            if not entity:
                return f"# Entity '{entity_name}' not found in lorien graph\n"
            ctx = self.get_entity_context(entity["id"])
            lines.append(f"## {entity['name']} ({entity['entity_type']})\n")
            if ctx["rules"]:
                lines.append("### Rules\n")
                for r in ctx["rules"]:
                    lines.append(f"- [{r['rule_type']}] {r['text']}")
                lines.append("")
            if ctx["facts"]:
                lines.append("### Facts\n")
                for f in ctx["facts"]:
                    lines.append(f"- {f['text']}")
                lines.append("")
        else:
            # Full export: group by entity
            entities = self.store.query(
                "MATCH (e:Entity) WHERE e.status = 'active' "
                "RETURN e.id, e.name, e.entity_type ORDER BY e.name"
            )

            for eid, ename, etype in entities:
                ctx = self.get_entity_context(eid)
                if not ctx["facts"] and not ctx["rules"]:
                    continue
                lines.append(f"## {ename} ({etype})\n")
                if ctx["rules"]:
                    for r in ctx["rules"]:
                        lines.append(f"- **[{r['rule_type']} p{r['priority']}]** {r['text']}")
                if ctx["facts"]:
                    for f in ctx["facts"]:
                        lines.append(f"- {f['text']}")
                lines.append("")

            # Global rules not tied to an entity
            global_rules = self.store.query(
                "MATCH (r:Rule) WHERE r.status = 'active' "
                "AND NOT EXISTS { MATCH (e:Entity)-[:HAS_RULE]->(r) } "
                "RETURN r.text, r.rule_type, r.priority ORDER BY r.priority DESC"
            )
            if global_rules:
                lines.append("## Global Rules\n")
                for text, rtype, priority in global_rules:
                    lines.append(f"- **[{rtype} p{priority}]** {text}")
                lines.append("")

            contradictions = self.find_contradictions()
            if contradictions:
                lines.append("## ⚠️ Contradictions\n")
                for c in contradictions:
                    lines.append(f"- \"{c['fact_a']['text']}\" ↔ \"{c['fact_b']['text']}\"")
                lines.append("")

        return "\n".join(lines) + "\n"
