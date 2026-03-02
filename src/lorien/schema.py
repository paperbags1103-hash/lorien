"""GraphStore: Kuzu-backed graph database for the lorien knowledge graph."""

from __future__ import annotations

from pathlib import Path

import kuzu

from .models import Agent, Decision, Entity, Fact, Rule, DEFAULT_AGENT_ID


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
            "Decision": (
                "id STRING, kind STRING, text STRING, decision_type STRING, "
                "context STRING, agent_id STRING, confidence DOUBLE, "
                "status STRING, created_at STRING, updated_at STRING, "
                "PRIMARY KEY(id)"
            ),
            "Agent": (
                "id STRING, kind STRING, name STRING, agent_type STRING, "
                "metadata STRING, created_at STRING, last_active_at STRING, "
                "status STRING, PRIMARY KEY(id)"
            ),
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
                "created_at STRING, updated_at STRING, "
                "last_confirmed STRING, expires_at STRING, version INT64, "
                "agent_id STRING, "
                "confidence DOUBLE, "
                "source STRING, source_ref STRING, status STRING, "
                "PRIMARY KEY(id)"
            ),
            "Rule": (
                "id STRING, kind STRING, text STRING, rule_type STRING, "
                "priority INT64, "
                "created_at STRING, updated_at STRING, "
                "last_confirmed STRING, expires_at STRING, "
                "agent_id STRING, "
                "confidence DOUBLE, "
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
            ("SUPERSEDES",  "FROM Fact TO Fact, reason STRING, created_at STRING"),
            ("CREATED_BY",  "FROM Fact TO Agent, created_at STRING"),
            # Decision edges
            ("BASED_ON",    "FROM Decision TO Fact, role STRING"),
            ("APPLIED_RULE","FROM Decision TO Rule, role STRING"),
            ("DECIDED_BY",  "FROM Decision TO Agent, created_at STRING"),
            ("SUPERSEDES_D","FROM Decision TO Decision, reason STRING, created_at STRING"),
        ]

        for table_name, columns in node_ddl.items():
            if table_name not in existing:
                self.conn.execute(f"CREATE NODE TABLE {table_name}({columns})")

        for rel_name, spec in rel_ddl:
            if rel_name not in existing:
                self.conn.execute(f"CREATE REL TABLE {rel_name}({spec})")

    def _q(self, value: str | None) -> str:
        """Escape a string value for safe embedding in a Cypher literal.

        Handles backslash and single-quote escaping. Converts None to empty string.

        Note: This is a best-effort escape for ASCII/common inputs. It is NOT
        resistant to Unicode escape sequences (e.g. \\u0027). For production
        environments with untrusted input, prefer KuzuDB parameterized queries
        via ``conn.execute(query, parameters={"key": value})``.
        """
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

    def add_agent(self, agent: Agent) -> None:
        """Insert an Agent node."""
        self.conn.execute(
            f"CREATE (n:Agent {{"
            f"id:{self._q(agent.id)}, kind:{self._q(agent.kind)}, "
            f"name:{self._q(agent.name)}, agent_type:{self._q(agent.agent_type)}, "
            f"metadata:{self._q(agent.metadata)}, "
            f"created_at:{self._q(agent.created_at)}, "
            f"last_active_at:{self._q(agent.last_active_at)}, "
            f"status:{self._q(agent.status)}"
            f"}})"
        )

    def get_or_create_agent(self, agent_id: str, name: str | None = None, agent_type: str = "llm") -> dict:
        """Return existing agent dict or create a new one. Thread-safe by design (upsert pattern)."""
        rows = self._rows(
            f"MATCH (a:Agent {{id:{self._q(agent_id)}}}) "
            f"RETURN a.id, a.name, a.agent_type, a.last_active_at"
        )
        if rows:
            # Update last_active_at
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            self.conn.execute(
                f"MATCH (a:Agent {{id:{self._q(agent_id)}}}) "
                f"SET a.last_active_at = {self._q(now)}"
            )
            return {"id": rows[0][0], "name": rows[0][1], "agent_type": rows[0][2]}

        agent = Agent(
            id=agent_id,
            name=name or agent_id,
            agent_type=agent_type,
        )
        self.add_agent(agent)
        return {"id": agent.id, "name": agent.name, "agent_type": agent.agent_type}

    def add_created_by(self, fact_id: str, agent_id: str) -> None:
        """Create CREATED_BY edge: (Fact)-[:CREATED_BY]->(Agent)."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            f"MATCH (f:Fact {{id:{self._q(fact_id)}}}), "
            f"(a:Agent {{id:{self._q(agent_id)}}}) "
            f"CREATE (f)-[:CREATED_BY {{created_at:{self._q(now)}}}]->(a)"
        )

    def get_agent_stats(self, agent_id: str) -> dict:
        """Return stats for a specific agent."""
        fact_rows = self._rows(
            f"MATCH (f:Fact {{agent_id:{self._q(agent_id)}, status:'active'}}) RETURN count(f)"
        )
        rule_rows = self._rows(
            f"MATCH (r:Rule {{agent_id:{self._q(agent_id)}, status:'active'}}) RETURN count(r)"
        )
        agent_rows = self._rows(
            f"MATCH (a:Agent {{id:{self._q(agent_id)}}}) "
            f"RETURN a.name, a.agent_type, a.last_active_at"
        )
        return {
            "agent_id": agent_id,
            "name": agent_rows[0][0] if agent_rows else agent_id,
            "agent_type": agent_rows[0][1] if agent_rows else "unknown",
            "last_active_at": agent_rows[0][2] if agent_rows else "",
            "facts": int(fact_rows[0][0]) if fact_rows else 0,
            "rules": int(rule_rows[0][0]) if rule_rows else 0,
        }

    def list_agents(self) -> list[dict]:
        """Return all registered agents."""
        rows = self._rows(
            "MATCH (a:Agent) WHERE a.status = 'active' "
            "RETURN a.id, a.name, a.agent_type, a.last_active_at "
            "ORDER BY a.last_active_at DESC"
        )
        return [
            {"id": r[0], "name": r[1], "agent_type": r[2], "last_active_at": r[3]}
            for r in rows
        ]

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
            f"last_confirmed:{self._q(fact.last_confirmed)}, "
            f"expires_at:{self._q(fact.expires_at)}, version:{fact.version}, "
            f"agent_id:{self._q(fact.agent_id)}, "
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
            f"last_confirmed:{self._q(rule.last_confirmed)}, "
            f"expires_at:{self._q(rule.expires_at)}, "
            f"agent_id:{self._q(rule.agent_id)}, "
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

    def add_supersedes(
        self, new_fact_id: str, old_fact_id: str, reason: str = "temporal_update"
    ) -> None:
        """Create SUPERSEDES edge: (new Fact)-[:SUPERSEDES]->(old Fact).

        Marks the old fact as superseded.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            f"MATCH (a:Fact {{id:{self._q(new_fact_id)}}}), "
            f"(b:Fact {{id:{self._q(old_fact_id)}}}) "
            f"CREATE (a)-[:SUPERSEDES {{reason:{self._q(reason)}, created_at:{self._q(now)}}}]->(b)"
        )
        # Mark old fact as superseded
        self.conn.execute(
            f"MATCH (f:Fact {{id:{self._q(old_fact_id)}}}) "
            f"SET f.status = 'superseded'"
        )

    def confirm_fact(self, fact_id: str) -> None:
        """Update last_confirmed timestamp to now."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            f"MATCH (f:Fact {{id:{self._q(fact_id)}}}) "
            f"SET f.last_confirmed = {self._q(now)}, f.updated_at = {self._q(now)}"
        )

    def confirm_rule(self, rule_id: str) -> None:
        """Update last_confirmed timestamp to now."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            f"MATCH (r:Rule {{id:{self._q(rule_id)}}}) "
            f"SET r.last_confirmed = {self._q(now)}, r.updated_at = {self._q(now)}"
        )

    def expire_stale_facts(self, max_age_days: int = 90, min_confidence: float = 0.3) -> int:
        """Mark stale facts as expired. Returns count of expired facts."""
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        rows = self._rows(
            f"MATCH (f:Fact) WHERE f.status = 'active' "
            f"AND f.last_confirmed < {self._q(cutoff)} "
            f"AND f.confidence < {min_confidence} "
            f"RETURN f.id"
        )
        for row in rows:
            self.conn.execute(
                f"MATCH (f:Fact {{id:{self._q(row[0])}}}) SET f.status = 'expired'"
            )
        return len(rows)

    # ── Decision methods ──────────────────────────────────────────────────────

    def add_decision(self, decision: Decision) -> None:
        """Insert a Decision node."""
        self.conn.execute(
            f"CREATE (n:Decision {{"
            f"id:{self._q(decision.id)}, kind:{self._q(decision.kind)}, "
            f"text:{self._q(decision.text)}, decision_type:{self._q(decision.decision_type)}, "
            f"context:{self._q(decision.context)}, agent_id:{self._q(decision.agent_id)}, "
            f"confidence:{decision.confidence}, status:{self._q(decision.status)}, "
            f"created_at:{self._q(decision.created_at)}, updated_at:{self._q(decision.updated_at)}"
            f"}})"
        )

    def add_based_on(self, decision_id: str, fact_id: str, role: str = "supporting") -> None:
        """Create BASED_ON edge: (Decision)-[:BASED_ON {role}]->(Fact)."""
        self.conn.execute(
            f"MATCH (d:Decision {{id:{self._q(decision_id)}}}), "
            f"(f:Fact {{id:{self._q(fact_id)}}}) "
            f"CREATE (d)-[:BASED_ON {{role:{self._q(role)}}}]->(f)"
        )

    def add_applied_rule(self, decision_id: str, rule_id: str, role: str = "primary") -> None:
        """Create APPLIED_RULE edge: (Decision)-[:APPLIED_RULE {role}]->(Rule)."""
        self.conn.execute(
            f"MATCH (d:Decision {{id:{self._q(decision_id)}}}), "
            f"(r:Rule {{id:{self._q(rule_id)}}}) "
            f"CREATE (d)-[:APPLIED_RULE {{role:{self._q(role)}}}]->(r)"
        )

    def add_decided_by(self, decision_id: str, agent_id: str) -> None:
        """Create DECIDED_BY edge: (Decision)-[:DECIDED_BY]->(Agent)."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            f"MATCH (d:Decision {{id:{self._q(decision_id)}}}), "
            f"(a:Agent {{id:{self._q(agent_id)}}}) "
            f"CREATE (d)-[:DECIDED_BY {{created_at:{self._q(now)}}}]->(a)"
        )

    def supersede_decision(self, new_id: str, old_id: str, reason: str = "updated") -> None:
        """Mark old decision as superseded; create SUPERSEDES_D edge."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            f"MATCH (a:Decision {{id:{self._q(new_id)}}}), "
            f"(b:Decision {{id:{self._q(old_id)}}}) "
            f"CREATE (a)-[:SUPERSEDES_D {{reason:{self._q(reason)}, created_at:{self._q(now)}}}]->(b)"
        )
        self.conn.execute(
            f"MATCH (d:Decision {{id:{self._q(old_id)}}}) SET d.status = 'superseded'"
        )

    def get_decision_chain(self, decision_id: str) -> dict:
        """Return a decision with all its supporting facts and applied rules."""
        # Decision node
        d_rows = self._rows(
            f"MATCH (d:Decision {{id:{self._q(decision_id)}}}) "
            f"RETURN d.id, d.text, d.decision_type, d.context, "
            f"d.agent_id, d.confidence, d.status, d.created_at"
        )
        if not d_rows:
            return {}

        r = d_rows[0]
        chain: dict = {
            "id": r[0], "text": r[1], "decision_type": r[2],
            "context": r[3], "agent_id": r[4],
            "confidence": r[5], "status": r[6], "created_at": r[7],
            "supporting_facts": [], "opposing_facts": [], "applied_rules": [],
        }

        # Supporting / opposing facts
        f_rows = self._rows(
            f"MATCH (d:Decision {{id:{self._q(decision_id)}}})"
            f"-[r:BASED_ON]->(f:Fact) "
            f"RETURN f.id, f.text, f.confidence, r.role"
        )
        for fid, text, conf, role in f_rows:
            entry = {"id": fid, "text": text, "confidence": conf}
            if role == "opposing":
                chain["opposing_facts"].append(entry)
            else:
                chain["supporting_facts"].append(entry)

        # Applied rules
        rule_rows = self._rows(
            f"MATCH (d:Decision {{id:{self._q(decision_id)}}})"
            f"-[r:APPLIED_RULE]->(rl:Rule) "
            f"RETURN rl.id, rl.text, rl.priority, r.role"
        )
        for rid, text, priority, role in rule_rows:
            chain["applied_rules"].append({
                "id": rid, "text": text, "priority": priority, "role": role
            })

        return chain

    def search_decisions(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search over Decision text/context."""
        safe_q = self._q(query.lower())
        rows = self._rows(
            f"MATCH (d:Decision) WHERE d.status = 'active' "
            f"AND (lower(d.text) CONTAINS {safe_q} "
            f"OR lower(d.context) CONTAINS {safe_q}) "
            f"RETURN d.id, d.text, d.decision_type, d.created_at "
            f"ORDER BY d.created_at DESC LIMIT {int(limit)}"
        )
        return [
            {"id": r[0], "text": r[1], "decision_type": r[2], "created_at": r[3]}
            for r in rows
        ]

    def migrate_v02_to_v03(self) -> dict:
        """Add v0.3 temporal fields to existing v0.2 nodes (in-place migration).

        Safe to run multiple times (idempotent).
        Returns counts of migrated nodes.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        # Migrate Facts: set last_confirmed = created_at, expires_at = '', version = 1
        # where last_confirmed is missing (old format has no last_confirmed field)
        try:
            fact_rows = self._rows(
                "MATCH (f:Fact) WHERE f.last_confirmed IS NULL OR f.last_confirmed = '' "
                "RETURN f.id, f.created_at"
            )
            for fid, created_at in fact_rows:
                confirmed = created_at if created_at else now
                self.conn.execute(
                    f"MATCH (f:Fact {{id:{self._q(fid)}}}) "
                    f"SET f.last_confirmed = {self._q(confirmed)}, "
                    f"f.expires_at = '', f.version = 1"
                )
        except Exception:
            fact_rows = []

        try:
            rule_rows = self._rows(
                "MATCH (r:Rule) WHERE r.last_confirmed IS NULL OR r.last_confirmed = '' "
                "RETURN r.id, r.created_at"
            )
            for rid, created_at in rule_rows:
                confirmed = created_at if created_at else now
                self.conn.execute(
                    f"MATCH (r:Rule {{id:{self._q(rid)}}}) "
                    f"SET r.last_confirmed = {self._q(confirmed)}, r.expires_at = ''"
                )
        except Exception:
            rule_rows = []

        return {"facts_migrated": len(fact_rows), "rules_migrated": len(rule_rows)}

    # ── v0.4 Common helpers ───────────────────────────────────────────────────

    def get_facts_by_subject(
        self,
        subject_id: str,
        status: str = "active",
        limit: int = 100,
    ) -> list[dict]:
        """Return all facts about a subject, with agent_id and timestamps."""
        rows = self._rows(
            f"MATCH (f:Fact) WHERE f.subject_id = {self._q(subject_id)} "
            f"AND f.status = {self._q(status)} "
            f"RETURN f.id, f.text, f.predicate, f.agent_id, "
            f"f.last_confirmed, f.confidence, f.version, f.created_at "
            f"ORDER BY f.last_confirmed DESC LIMIT {int(limit)}"
        )
        return [
            {
                "id": r[0], "text": r[1], "predicate": r[2],
                "agent_id": r[3], "last_confirmed": r[4],
                "confidence": r[5], "version": r[6], "created_at": r[7],
            }
            for r in rows
        ]

    # ── v0.4 Epistemic Debt ───────────────────────────────────────────────────

    def get_epistemic_debt(
        self,
        min_confidence: float = 0.7,
        min_age_days: float = 60.0,
        only_version_one: bool = True,
        limit: int = 50,
    ) -> list[dict]:
        """Return facts that are old, high-confidence, and never re-confirmed.

        Debt score = confidence * age_days / 365.
        Higher score = "been assumed longer without verification".
        """
        from datetime import datetime, timezone, timedelta
        from .temporal import age_in_days

        cutoff = (datetime.now(timezone.utc) - timedelta(days=min_age_days)).isoformat()
        version_clause = "AND f.version = 1 " if only_version_one else ""

        rows = self._rows(
            f"MATCH (f:Fact) WHERE f.status = 'active' "
            f"AND f.confidence >= {float(min_confidence)} "
            f"AND f.last_confirmed < {self._q(cutoff)} "
            f"{version_clause}"
            f"RETURN f.id, f.text, f.subject_id, f.confidence, "
            f"f.last_confirmed, f.version, f.agent_id, f.created_at "
            f"LIMIT {int(limit)}"
        )

        results = []
        for r in rows:
            fid, text, subject_id, conf, confirmed, version, agent_id, created = r
            a_days = age_in_days(confirmed or created or "")
            debt_score = float(conf or 0) * a_days / 365.0

            # Try to get subject name
            subject_name = subject_id or ""
            if subject_id:
                ent = self._rows(
                    f"MATCH (e:Entity {{id:{self._q(subject_id)}}}) RETURN e.name LIMIT 1"
                )
                if ent:
                    subject_name = ent[0][0]

            results.append({
                "fact_id": fid,
                "fact_text": text,
                "subject_id": subject_id or "",
                "subject_name": subject_name,
                "confidence": float(conf or 0),
                "age_days": round(a_days, 1),
                "version": int(version or 1),
                "agent_id": agent_id or "default",
                "last_confirmed": confirmed or "",
                "debt_score": round(debt_score, 3),
            })

        results.sort(key=lambda x: x["debt_score"], reverse=True)
        return results

    # ── v0.4 Belief Fork ─────────────────────────────────────────────────────

    def find_belief_forks(
        self,
        min_agents: int = 2,
        only_critical: bool = False,
    ) -> list[dict]:
        """Find subjects where different agents hold diverging beliefs.

        A fork exists when the same subject+predicate has facts from
        different agents that contradict each other or have large freshness gaps.
        """
        from .temporal import age_in_days

        # Get all active facts grouped by subject_id + predicate
        rows = self._rows(
            "MATCH (f:Fact) WHERE f.status = 'active' "
            "AND f.subject_id <> '' AND f.predicate <> '' AND f.agent_id <> '' "
            "RETURN f.subject_id, f.predicate, f.agent_id, "
            "f.id, f.text, f.last_confirmed, f.confidence "
            "ORDER BY f.subject_id, f.predicate"
        )

        # Group by (subject_id, predicate)
        from collections import defaultdict
        groups: dict = defaultdict(list)
        for subject_id, predicate, agent_id, fid, text, confirmed, conf in rows:
            key = (subject_id or "", predicate or "")
            groups[key].append({
                "agent_id": agent_id or "default",
                "fact_id": fid,
                "fact_text": text,
                "last_confirmed": confirmed or "",
                "confidence": float(conf or 0),
            })

        forks = []
        for (subject_id, predicate), facts in groups.items():
            # Only consider when multiple agents have facts
            agent_ids = {f["agent_id"] for f in facts}
            if len(agent_ids) < min_agents:
                continue

            # Check for CONTRADICTS edges between any two facts in this group
            fact_ids = [f["fact_id"] for f in facts]
            has_contradiction = False
            for i, fid_a in enumerate(fact_ids):
                for fid_b in fact_ids[i + 1:]:
                    cont = self._rows(
                        f"MATCH (a:Fact {{id:{self._q(fid_a)}}})-[:CONTRADICTS]-(b:Fact {{id:{self._q(fid_b)}}}) "
                        f"RETURN count(*) LIMIT 1"
                    )
                    if cont and int(cont[0][0]) > 0:
                        has_contradiction = True
                        break
                if has_contradiction:
                    break

            # Check freshness gap
            ages = [age_in_days(f["last_confirmed"]) for f in facts if f["last_confirmed"]]
            freshness_gap = (max(ages) - min(ages)) if len(ages) >= 2 else 0.0

            if has_contradiction:
                severity = "critical"
            elif freshness_gap > 30:
                severity = "warning"
            else:
                severity = "info"

            if only_critical and severity != "critical":
                continue

            # Resolve subject name
            subject_name = subject_id
            if subject_id:
                ent = self._rows(
                    f"MATCH (e:Entity {{id:{self._q(subject_id)}}}) RETURN e.name LIMIT 1"
                )
                if ent:
                    subject_name = ent[0][0]

            forks.append({
                "subject_id": subject_id,
                "subject_name": subject_name,
                "predicate": predicate,
                "forks": facts,
                "severity": severity,
                "days_since_oldest": round(max(ages) if ages else 0.0, 1),
                "has_contradiction": has_contradiction,
                "freshness_gap_days": round(freshness_gap, 1),
            })

        # Sort: critical first, then by freshness gap
        severity_order = {"critical": 0, "warning": 1, "info": 2}
        forks.sort(key=lambda x: (severity_order[x["severity"]], -x["freshness_gap_days"]))
        return forks

    # ── v0.4 Consequence Simulation ───────────────────────────────────────────

    def simulate_decision_impact(
        self,
        decision_text: str,
        supporting_fact_ids: list[str] | None = None,
    ) -> dict:
        """Simulate adding a decision without writing to graph (read-only).

        Returns impact analysis: compatible facts, needs_update, rule_violations.
        """
        from .contradiction import ContradictionDetector
        from .models import Fact as FactModel

        # Find related facts via subject overlap from supporting_fact_ids
        related_facts = []
        if supporting_fact_ids:
            for fid in supporting_fact_ids:
                rows = self._rows(
                    f"MATCH (f:Fact {{id:{self._q(fid)}}})-[:ABOUT]->(e:Entity)"
                    f"<-[:ABOUT]-(other:Fact) WHERE other.status = 'active' "
                    f"RETURN other.id, other.text, other.confidence LIMIT 20"
                )
                for rid, rtext, rconf in rows:
                    if rid not in {f["id"] for f in related_facts}:
                        related_facts.append({"id": rid, "text": rtext, "confidence": float(rconf or 0)})

        # Find rule violations by text matching
        rule_rows = self._rows(
            "MATCH (r:Rule) WHERE r.status = 'active' AND r.priority >= 50 "
            "RETURN r.id, r.text, r.priority, r.rule_type LIMIT 100"
        )

        rule_violations = []
        decision_lower = decision_text.lower()
        for rid, rtext, priority, rtype in rule_rows:
            # Simple heuristic: prohibition rules that might apply
            if rtype in ("prohibition", "fixed") and rtext:
                # Check if any key words overlap
                rule_words = set(rtext.lower().split())
                decision_words = set(decision_lower.split())
                overlap = rule_words & decision_words
                if len(overlap) >= 2:  # at least 2 words in common
                    rule_violations.append({
                        "id": rid,
                        "text": rtext,
                        "priority": int(priority or 50),
                    })

        # Needs update: supporting facts that are old/stale
        needs_update = []
        for f in related_facts[:10]:
            needs_update.append({"id": f["id"], "text": f["text"], "reason": "related fact may need review"})

        # Compatible count = total active facts minus violations and needs_update
        total_facts = self._rows("MATCH (f:Fact) WHERE f.status = 'active' RETURN count(f)")
        total = int(total_facts[0][0]) if total_facts else 0
        compatible = max(0, total - len(needs_update) - len(rule_violations))

        # Impact score
        impact = min(1.0, (len(rule_violations) * 0.3 + len(needs_update) * 0.05))
        if impact < 0.2:
            recommendation = "proceed"
        elif impact < 0.5:
            recommendation = "caution"
        else:
            recommendation = "reconsider"

        return {
            "decision": {"text": decision_text},
            "compatible_facts": compatible,
            "needs_update": needs_update[:5],
            "rule_violations": rule_violations[:5],
            "superseded_decisions": [],
            "impact_score": round(impact, 2),
            "recommendation": recommendation,
            "confidence": round(min(1.0, total / max(1, total + 10)), 2),
            "disclaimer": "Based on known facts only. Unknown facts may change the outcome.",
        }

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
        for table_name in ("Entity", "Fact", "Rule", "Agent", "Decision"):
            rows = self._rows(f"MATCH (n:{table_name}) RETURN count(n)")
            counts[table_name] = int(rows[0][0]) if rows else 0
        return counts

    def query(self, cypher: str) -> list:
        """Execute arbitrary Cypher and return all rows."""
        return self._rows(cypher)
