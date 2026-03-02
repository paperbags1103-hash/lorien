"""GraphStore: Kuzu-backed graph database for the lorien knowledge graph."""

from __future__ import annotations

from pathlib import Path

import kuzu

from .models import Entity, Fact, Rule


class GraphStore:
    """Low-level interface to the Kuzu embedded graph database.

    Handles schema creation, node/edge insertion, and raw Cypher queries.
    All string values are escaped via _q() before insertion to prevent
    Cypher injection.
    """

    def __init__(self, db_path: str | Path = "~/.lorien/db") -> None:
        # Kuzu 0.8.x uses db_path as a FILE path (creates its own internal structure).
        # Ensure the parent directory exists; Kuzu handles the rest.
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = kuzu.Database(str(self.db_path))
        self.conn = kuzu.Connection(self.db)
        self._create_schema()

    def _existing_tables(self) -> set[str]:
        """Return the set of table names already in the database."""
        result = self.conn.execute("CALL show_tables() RETURN name")
        tables: set[str] = set()
        while result.has_next():
            row = result.get_next()
            if row:
                tables.add(str(row[0]))
        return tables

    def _create_schema(self) -> None:
        """Create node and relationship tables if they do not already exist. Idempotent."""
        existing = self._existing_tables()

        node_ddl: dict[str, str] = {
            "Entity": (
                "id STRING, kind STRING, name STRING, entity_type STRING, "
                "aliases STRING, description STRING, "
                "created_at STRING, updated_at STRING, confidence DOUBLE, "
                "source STRING, source_ref STRING, status STRING, "
                "canonical_key STRING, PRIMARY KEY(id)"
            ),
            "Fact": (
                "id STRING, kind STRING, text STRING, fact_type STRING, "
                "subject_id STRING, predicate STRING, object_id STRING, "
                "valid_from STRING, valid_to STRING, negated BOOL, "
                "created_at STRING, updated_at STRING, confidence DOUBLE, "
                "source STRING, source_ref STRING, status STRING, "
                "PRIMARY KEY(id)"
            ),
            "Rule": (
                "id STRING, kind STRING, text STRING, rule_type STRING, "
                "priority INT64, "
                "created_at STRING, updated_at STRING, confidence DOUBLE, "
                "source STRING, source_ref STRING, status STRING, "
                "PRIMARY KEY(id)"
            ),
        }

        rel_ddl: list[tuple[str, str]] = [
            ("ABOUT",       "FROM Fact TO Entity"),
            ("HAS_RULE",    "FROM Entity TO Rule"),
            ("RELATED_TO",  "FROM Entity TO Entity, relation STRING"),
            ("CAUSED",      "FROM Fact TO Fact"),
            ("CONTRADICTS", "FROM Fact TO Fact"),
        ]

        for table_name, columns in node_ddl.items():
            if table_name not in existing:
                self.conn.execute(f"CREATE NODE TABLE {table_name}({columns})")

        for rel_name, spec in rel_ddl:
            if rel_name not in existing:
                self.conn.execute(f"CREATE REL TABLE {rel_name}({spec})")

    def _q(self, value: str | None) -> str:
        """Escape a string value for safe embedding in a Cypher literal."""
        if value is None:
            return "''"
        value = value.replace("\\", "\\\\")
        value = value.replace("'", "\\'")
        return f"'{value}'"

    def _rows(self, cypher: str) -> list:
        """Execute a Cypher query and return all rows as a list of lists."""
        result = self.conn.execute(cypher)
        rows: list = []
        while result.has_next():
            rows.append(result.get_next())
        return rows

    def add_entity(self, entity: Entity) -> None:
        """Insert an Entity node."""
        self.conn.execute(
            f"CREATE (n:Entity {{"
            f"id:{self._q(entity.id)}, kind:{self._q(entity.kind)}, "
            f"name:{self._q(entity.name)}, entity_type:{self._q(entity.entity_type)}, "
            f"aliases:{self._q(entity.aliases)}, description:{self._q(entity.description)}, "
            f"created_at:{self._q(entity.created_at)}, updated_at:{self._q(entity.updated_at)}, "
            f"confidence:{entity.confidence}, source:{self._q(entity.source)}, "
            f"source_ref:{self._q(entity.source_ref)}, status:{self._q(entity.status)}, "
            f"canonical_key:{self._q(entity.canonical_key)}"
            f"}})"
        )

    def add_fact(self, fact: Fact) -> None:
        """Insert a Fact node."""
        negated_str = "true" if fact.negated else "false"
        self.conn.execute(
            f"CREATE (n:Fact {{"
            f"id:{self._q(fact.id)}, kind:{self._q(fact.kind)}, "
            f"text:{self._q(fact.text)}, fact_type:{self._q(fact.fact_type)}, "
            f"subject_id:{self._q(fact.subject_id)}, predicate:{self._q(fact.predicate)}, "
            f"object_id:{self._q(fact.object_id)}, valid_from:{self._q(fact.valid_from)}, "
            f"valid_to:{self._q(fact.valid_to)}, negated:{negated_str}, "
            f"created_at:{self._q(fact.created_at)}, updated_at:{self._q(fact.updated_at)}, "
            f"confidence:{fact.confidence}, source:{self._q(fact.source)}, "
            f"source_ref:{self._q(fact.source_ref)}, status:{self._q(fact.status)}"
            f"}})"
        )

    def add_rule(self, rule: Rule) -> None:
        """Insert a Rule node."""
        self.conn.execute(
            f"CREATE (n:Rule {{"
            f"id:{self._q(rule.id)}, kind:{self._q(rule.kind)}, "
            f"text:{self._q(rule.text)}, rule_type:{self._q(rule.rule_type)}, "
            f"priority:{rule.priority}, "
            f"created_at:{self._q(rule.created_at)}, updated_at:{self._q(rule.updated_at)}, "
            f"confidence:{rule.confidence}, source:{self._q(rule.source)}, "
            f"source_ref:{self._q(rule.source_ref)}, status:{self._q(rule.status)}"
            f"}})"
        )

    def add_about(self, fact_id: str, entity_id: str) -> None:
        """Create ABOUT edge: (Fact)-[:ABOUT]->(Entity)."""
        self.conn.execute(
            f"MATCH (f:Fact {{id:{self._q(fact_id)}}}), "
            f"(e:Entity {{id:{self._q(entity_id)}}}) "
            f"CREATE (f)-[:ABOUT]->(e)"
        )

    def add_has_rule(self, entity_id: str, rule_id: str) -> None:
        """Create HAS_RULE edge: (Entity)-[:HAS_RULE]->(Rule)."""
        self.conn.execute(
            f"MATCH (e:Entity {{id:{self._q(entity_id)}}}), "
            f"(r:Rule {{id:{self._q(rule_id)}}}) "
            f"CREATE (e)-[:HAS_RULE]->(r)"
        )

    def add_related_to(self, from_id: str, to_id: str, relation: str = "related_to") -> None:
        """Create RELATED_TO edge with semantic type in `relation` property."""
        self.conn.execute(
            f"MATCH (a:Entity {{id:{self._q(from_id)}}}), "
            f"(b:Entity {{id:{self._q(to_id)}}}) "
            f"CREATE (a)-[:RELATED_TO {{relation:{self._q(relation)}}}]->(b)"
        )

    def add_caused(self, from_fact_id: str, to_fact_id: str) -> None:
        """Create CAUSED edge: (Fact)-[:CAUSED]->(Fact)."""
        self.conn.execute(
            f"MATCH (a:Fact {{id:{self._q(from_fact_id)}}}), "
            f"(b:Fact {{id:{self._q(to_fact_id)}}}) "
            f"CREATE (a)-[:CAUSED]->(b)"
        )

    def add_contradicts(self, fact_id_a: str, fact_id_b: str) -> None:
        """Create CONTRADICTS edge: (Fact)-[:CONTRADICTS]->(Fact)."""
        self.conn.execute(
            f"MATCH (a:Fact {{id:{self._q(fact_id_a)}}}), "
            f"(b:Fact {{id:{self._q(fact_id_b)}}}) "
            f"CREATE (a)-[:CONTRADICTS]->(b)"
        )

    def find_entity_by_canonical_key(self, canonical_key: str) -> dict | None:
        rows = self._rows(
            f"MATCH (e:Entity) WHERE e.canonical_key = {self._q(canonical_key)} "
            f"AND e.status = 'active' RETURN e.id, e.name, e.canonical_key LIMIT 1"
        )
        return {"id": rows[0][0], "name": rows[0][1], "canonical_key": rows[0][2]} if rows else None

    def find_entity_by_alias(self, alias: str, entity_type: str | None = None) -> dict | None:
        type_clause = f"AND e.entity_type = {self._q(entity_type)} " if entity_type else ""
        rows = self._rows(
            f"MATCH (e:Entity) WHERE e.status = 'active' {type_clause}"
            f"AND (lower(e.name) = {self._q(alias.lower())} "
            f"OR (',' + e.aliases + ',') CONTAINS (',' + {self._q(alias)} + ',')) "
            f"RETURN e.id, e.name, e.canonical_key LIMIT 1"
        )
        return {"id": rows[0][0], "name": rows[0][1], "canonical_key": rows[0][2]} if rows else None

    def update_entity_status(self, entity_id: str, status: str) -> None:
        """Soft-update an entity's status (e.g. 'active' → 'superseded')."""
        self.conn.execute(
            f"MATCH (e:Entity {{id:{self._q(entity_id)}}}) "
            f"SET e.status = {self._q(status)}"
        )

    def count_nodes(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for table_name in ("Entity", "Fact", "Rule"):
            rows = self._rows(f"MATCH (n:{table_name}) RETURN count(n)")
            counts[table_name] = int(rows[0][0]) if rows else 0
        return counts

    def query(self, cypher: str) -> list:
        """Execute arbitrary Cypher and return all rows."""
        return self._rows(cypher)
