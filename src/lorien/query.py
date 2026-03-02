from __future__ import annotations

from datetime import datetime, timezone

from .schema import GraphStore


class KnowledgeGraph:
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    def get_entity(self, name: str) -> dict | None:
        rows = self.store.query(
            f"MATCH (e:Entity) WHERE lower(e.name) = lower('{name}') "
            f"AND e.status = 'active' RETURN e.id, e.name, e.entity_type, e.canonical_key LIMIT 1"
        )
        if not rows:
            return None
        row = rows[0]
        return {"id": row[0], "name": row[1], "entity_type": row[2], "canonical_key": row[3]}

    def get_entity_context(self, entity_id: str) -> dict:
        facts = self.store.query(
            f"MATCH (f:Fact)-[:ABOUT]->(e:Entity) WHERE e.id = '{entity_id}' "
            f"AND f.status = 'active' RETURN f.id, f.text, f.confidence, f.created_at "
            f"ORDER BY f.created_at DESC"
        )
        rules = self.store.query(
            f"MATCH (e:Entity)-[:HAS_RULE]->(r:Rule) WHERE e.id = '{entity_id}' "
            f"AND r.status = 'active' RETURN r.id, r.text, r.rule_type, r.priority "
            f"ORDER BY r.priority DESC"
        )
        return {
            "entity_id": entity_id,
            "facts": [
                {"id": row[0], "text": row[1], "confidence": row[2], "created_at": row[3]}
                for row in facts
            ],
            "rules": [
                {"id": row[0], "text": row[1], "rule_type": row[2], "priority": row[3]}
                for row in rules
            ],
        }

    def find_contradictions(self) -> list[dict]:
        rows = self.store.query(
            "MATCH (a:Fact)-[:CONTRADICTS]->(b:Fact) "
            "WHERE a.status = 'active' AND b.status = 'active' "
            "RETURN a.id, a.text, b.id, b.text, a.created_at, b.created_at "
            "ORDER BY a.created_at DESC"
        )
        return [
            {
                "fact_a": {"id": row[0], "text": row[1], "created_at": row[4]},
                "fact_b": {"id": row[2], "text": row[3], "created_at": row[5]},
            }
            for row in rows
        ]

    def get_causal_chain(self, fact_id: str, depth: int = 3) -> list[dict]:
        rows = self.store.query(
            f"MATCH (s:Fact)-[:CAUSED*1..{depth}]->(e:Fact) "
            f"WHERE s.id = '{fact_id}' AND e.status = 'active' "
            f"RETURN e.id, e.text, e.confidence"
        )
        return [{"id": row[0], "text": row[1], "confidence": row[2]} for row in rows]

    def get_recent_facts(self, limit: int = 20) -> list[dict]:
        rows = self.store.query(
            f"MATCH (f:Fact) WHERE f.status = 'active' "
            f"RETURN f.id, f.text, f.confidence, f.source, f.created_at "
            f"ORDER BY f.created_at DESC LIMIT {limit}"
        )
        return [
            {
                "id": row[0],
                "text": row[1],
                "confidence": row[2],
                "source": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    def get_active_rules(self, entity_id: str | None = None) -> list[dict]:
        if entity_id:
            rows = self.store.query(
                f"MATCH (e:Entity)-[:HAS_RULE]->(r:Rule) WHERE e.id = '{entity_id}' "
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
            {
                "id": row[0],
                "text": row[1],
                "rule_type": row[2],
                "priority": row[3],
                "confidence": row[4],
            }
            for row in rows
        ]

    def export_to_memory_md(self, entity_name: str | None = None) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = [f"# lorien Export ({now})\n"]

        rules = self.get_active_rules()
        if rules:
            lines.append("## Rules\n")
            for rule in rules:
                lines.append(f"- [{rule['rule_type']}] {rule['text']}")
            lines.append("")

        facts = self.get_recent_facts(50)
        if facts:
            lines.append("## Recent Facts\n")
            for fact in facts:
                lines.append(f"- {fact['text']}")

        contradictions = self.find_contradictions()
        if contradictions:
            lines.append("\n## ⚠️ Contradictions\n")
            for item in contradictions:
                lines.append(f"- \"{item['fact_a']['text']}\" ↔ \"{item['fact_b']['text']}\"")

        return "\n".join(lines) + "\n"
