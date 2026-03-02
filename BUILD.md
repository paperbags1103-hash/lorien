# lorien v0.1 — Full Implementation

Completely rewrite the existing scaffold. Delete all existing Python files in src/lorien/ and tests/, then implement from scratch per this spec.

## Project structure
```
src/lorien/
├── __init__.py
├── models.py
├── schema.py
├── ingest.py
├── query.py
└── cli.py
tests/
├── __init__.py
├── conftest.py
├── test_schema.py
├── test_query.py
└── test_ingest.py
```

---

## models.py

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _uid() -> str:
    return uuid.uuid4().hex[:12]

@dataclass
class Entity:
    name: str
    entity_type: str                    # person, org, project, tool, concept, place
    id: str = field(default_factory=_uid)
    kind: str = "entity"
    aliases: str = ""                   # comma-separated
    description: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    confidence: float = 1.0
    source: str = ""
    source_ref: str = ""
    status: str = "active"
    canonical_key: str = ""

    def __post_init__(self):
        if not self.canonical_key:
            import re
            n = re.sub(r"[^\w가-힣]", "", self.name.lower().replace(" ", "_"))
            self.canonical_key = f"{self.entity_type}:{n}"

@dataclass
class Fact:
    text: str
    id: str = field(default_factory=_uid)
    kind: str = "fact"
    fact_type: str = "statement"        # statement, preference, observation, biographical, technical
    subject_id: str = ""
    predicate: str = ""
    object_id: str = ""
    valid_from: str = ""
    valid_to: str = ""
    negated: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    confidence: float = 1.0
    source: str = ""
    source_ref: str = ""
    status: str = "active"

@dataclass
class Rule:
    text: str
    id: str = field(default_factory=_uid)
    kind: str = "rule"
    rule_type: str = "preference"       # prohibition, fixed, preference, instruction
    priority: int = 50                  # 0-100, higher = stronger
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    confidence: float = 1.0
    source: str = ""
    source_ref: str = ""
    status: str = "active"
```

---

## schema.py — GraphStore

```python
from __future__ import annotations
from pathlib import Path
import kuzu
from .models import Entity, Fact, Rule

class GraphStore:
    def __init__(self, db_path: str | Path = "~/.lorien/db") -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.mkdir(parents=True, exist_ok=True)
        self.db = kuzu.Database(str(self.db_path))
        self.conn = kuzu.Connection(self.db)
        self._create_schema()

    def _existing_tables(self) -> set[str]:
        result = self.conn.execute("CALL show_tables() RETURN name")
        tables = set()
        while result.has_next():
            tables.add(result.get_next()[0])
        return tables

    def _create_schema(self) -> None:
        existing = self._existing_tables()
        node_ddl = {
            "Entity": (
                "id STRING, kind STRING, name STRING, entity_type STRING, "
                "aliases STRING, description STRING, "
                "created_at STRING, updated_at STRING, confidence DOUBLE, "
                "source STRING, source_ref STRING, status STRING, canonical_key STRING, "
                "PRIMARY KEY(id)"
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
        rel_ddl = [
            ("ABOUT",        "FROM Fact TO Entity"),
            ("HAS_RULE",     "FROM Entity TO Rule"),
            ("RELATED_TO",   "FROM Entity TO Entity, relation STRING"),
            ("CAUSED",       "FROM Fact TO Fact"),
            ("CONTRADICTS",  "FROM Fact TO Fact"),
        ]
        for tname, cols in node_ddl.items():
            if tname not in existing:
                self.conn.execute(f"CREATE NODE TABLE {tname}({cols})")
        for rname, spec in rel_ddl:
            if rname not in existing:
                self.conn.execute(f"CREATE REL TABLE {rname}({spec})")

    def _q(self, s: str) -> str:
        """Escape string for Cypher single-quoted literals."""
        s = s.replace("\\", "\\\\")
        s = s.replace("'", "\\'")
        return f"'{s}'"

    def _rows(self, cypher: str) -> list:
        result = self.conn.execute(cypher)
        rows = []
        while result.has_next():
            rows.append(result.get_next())
        return rows

    def add_entity(self, e: Entity) -> None:
        self.conn.execute(
            f"CREATE (n:Entity {{id:{self._q(e.id)}, kind:{self._q(e.kind)}, "
            f"name:{self._q(e.name)}, entity_type:{self._q(e.entity_type)}, "
            f"aliases:{self._q(e.aliases)}, description:{self._q(e.description)}, "
            f"created_at:{self._q(e.created_at)}, updated_at:{self._q(e.updated_at)}, "
            f"confidence:{e.confidence}, source:{self._q(e.source)}, "
            f"source_ref:{self._q(e.source_ref)}, status:{self._q(e.status)}, "
            f"canonical_key:{self._q(e.canonical_key)}}})"
        )

    def add_fact(self, f: Fact) -> None:
        neg = "true" if f.negated else "false"
        self.conn.execute(
            f"CREATE (n:Fact {{id:{self._q(f.id)}, kind:{self._q(f.kind)}, "
            f"text:{self._q(f.text)}, fact_type:{self._q(f.fact_type)}, "
            f"subject_id:{self._q(f.subject_id)}, predicate:{self._q(f.predicate)}, "
            f"object_id:{self._q(f.object_id)}, valid_from:{self._q(f.valid_from)}, "
            f"valid_to:{self._q(f.valid_to)}, negated:{neg}, "
            f"created_at:{self._q(f.created_at)}, updated_at:{self._q(f.updated_at)}, "
            f"confidence:{f.confidence}, source:{self._q(f.source)}, "
            f"source_ref:{self._q(f.source_ref)}, status:{self._q(f.status)}}})"
        )

    def add_rule(self, r: Rule) -> None:
        self.conn.execute(
            f"CREATE (n:Rule {{id:{self._q(r.id)}, kind:{self._q(r.kind)}, "
            f"text:{self._q(r.text)}, rule_type:{self._q(r.rule_type)}, "
            f"priority:{r.priority}, "
            f"created_at:{self._q(r.created_at)}, updated_at:{self._q(r.updated_at)}, "
            f"confidence:{r.confidence}, source:{self._q(r.source)}, "
            f"source_ref:{self._q(r.source_ref)}, status:{self._q(r.status)}}})"
        )

    def add_about(self, fact_id: str, entity_id: str) -> None:
        self.conn.execute(
            f"MATCH (f:Fact {{id:{self._q(fact_id)}}}), (e:Entity {{id:{self._q(entity_id)}}}) "
            f"CREATE (f)-[:ABOUT]->(e)"
        )

    def add_has_rule(self, entity_id: str, rule_id: str) -> None:
        self.conn.execute(
            f"MATCH (e:Entity {{id:{self._q(entity_id)}}}), (r:Rule {{id:{self._q(rule_id)}}}) "
            f"CREATE (e)-[:HAS_RULE]->(r)"
        )

    def add_related_to(self, from_id: str, to_id: str, relation: str = "") -> None:
        self.conn.execute(
            f"MATCH (a:Entity {{id:{self._q(from_id)}}}), (b:Entity {{id:{self._q(to_id)}}}) "
            f"CREATE (a)-[:RELATED_TO {{relation:{self._q(relation)}}}]->(b)"
        )

    def add_caused(self, from_fact_id: str, to_fact_id: str) -> None:
        self.conn.execute(
            f"MATCH (a:Fact {{id:{self._q(from_fact_id)}}}), (b:Fact {{id:{self._q(to_fact_id)}}}) "
            f"CREATE (a)-[:CAUSED]->(b)"
        )

    def add_contradicts(self, fact_id_a: str, fact_id_b: str) -> None:
        self.conn.execute(
            f"MATCH (a:Fact {{id:{self._q(fact_id_a)}}}), (b:Fact {{id:{self._q(fact_id_b)}}}) "
            f"CREATE (a)-[:CONTRADICTS]->(b)"
        )

    def find_entity_by_canonical_key(self, canonical_key: str) -> dict | None:
        rows = self._rows(
            f"MATCH (e:Entity) WHERE e.canonical_key = {self._q(canonical_key)} "
            f"AND e.status = 'active' RETURN e.id, e.name, e.canonical_key LIMIT 1"
        )
        return {"id": rows[0][0], "name": rows[0][1], "canonical_key": rows[0][2]} if rows else None

    def find_entity_by_alias(self, alias: str) -> dict | None:
        key = alias.lower().replace(" ", "_")
        rows = self._rows(
            f"MATCH (e:Entity) WHERE e.status = 'active' "
            f"AND (lower(e.name) = {self._q(alias.lower())} "
            f"OR e.aliases CONTAINS {self._q(alias)}) "
            f"RETURN e.id, e.name, e.canonical_key LIMIT 1"
        )
        return {"id": rows[0][0], "name": rows[0][1], "canonical_key": rows[0][2]} if rows else None

    def count_nodes(self) -> dict[str, int]:
        counts = {}
        for tname in ["Entity", "Fact", "Rule"]:
            rows = self._rows(f"MATCH (n:{tname}) RETURN count(n)")
            counts[tname] = rows[0][0] if rows else 0
        return counts

    def query(self, cypher: str) -> list:
        return self._rows(cypher)
```

---

## ingest.py — LorienIngester

```python
from __future__ import annotations
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import GraphStore
from .models import Entity, Fact, Rule

@dataclass
class ExtractedEntity:
    name: str
    entity_type: str = "concept"
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    confidence: float = 0.8

@dataclass
class ExtractedFact:
    text: str
    subject: str = "user"
    predicate: str = "noted"
    object: str | None = None
    fact_type: str = "observation"
    confidence: float = 0.8
    negated: bool = False

@dataclass
class ExtractedRule:
    text: str
    subject: str = "user"
    rule_type: str = "preference"
    priority: int = 50
    confidence: float = 0.9

@dataclass
class ExtractedRelation:
    source: str
    target: str
    rel_type: str = "RELATED_TO"
    confidence: float = 0.7

@dataclass
class ExtractedTriples:
    entities: list[ExtractedEntity] = field(default_factory=list)
    facts: list[ExtractedFact] = field(default_factory=list)
    rules: list[ExtractedRule] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)

@dataclass
class IngestResult:
    entities_added: int = 0
    facts_added: int = 0
    rules_added: int = 0
    edges_added: int = 0
    errors: list[str] = field(default_factory=list)

RULE_MARKERS = {
    "절대": ("prohibition", 100),
    "금지": ("prohibition", 95),
    "하지 말": ("prohibition", 90),
    "never": ("prohibition", 90),
    "must not": ("prohibition", 90),
    "don't": ("prohibition", 85),
    "고정": ("fixed", 85),
    "항상": ("fixed", 80),
    "always": ("fixed", 80),
    "반드시": ("instruction", 75),
    "must": ("instruction", 75),
}

SYSTEM_PROMPT = """You are a knowledge graph extraction assistant. Extract structured knowledge from text as JSON.

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
priority: 0-100 (higher = stronger)
rel_type: RELATED_TO, CAUSED, CONTRADICTS

Rules: be conservative with confidence. Low confidence is better than wrong data."""

USER_PROMPT = """Extract knowledge triples from this text:

{text}

Return ONLY JSON, no explanation."""

# MEMORY.md section header regex
HEADER_RE = re.compile(r"^#{1,6}\s+")


class LorienIngester:
    def __init__(
        self,
        store: GraphStore,
        llm_model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        self.store = store
        self.llm_model = llm_model
        self.api_key = api_key
        self.base_url = base_url or "https://api.openai.com/v1"
        self._entity_cache: dict[str, str] = {}  # canonical_key -> entity_id

    def ingest_text(self, text: str, source: str = "manual") -> IngestResult:
        text = text.strip()
        if not text:
            return IngestResult(errors=["Empty text"])
        triples = self._llm_extract(text) if (self.llm_model and self.api_key) else None
        if triples is None:
            triples = self._keyword_extract(text)
        return self._store_triples(triples, source)

    def ingest_memory_md(self, path: str) -> IngestResult:
        """Parse MEMORY.md into sections and ingest each."""
        content = Path(path).read_text(encoding="utf-8")
        result = IngestResult()
        lines = content.split("\n")
        sections: list[tuple[str, list[str]]] = []
        current_header = "general"
        current_lines: list[str] = []
        for i, line in enumerate(lines):
            if HEADER_RE.match(line):
                if current_lines:
                    sections.append((current_header, current_lines))
                current_header = HEADER_RE.sub("", line).strip()
                current_lines = []
                source_ref = f"{path}:{i+1}"
            else:
                current_lines.append(line)
        if current_lines:
            sections.append((current_header, current_lines))

        for header, sec_lines in sections:
            body = "\n".join(sec_lines).strip()
            if not body:
                continue
            section_source = f"MEMORY.md:{header}"
            r = self.ingest_text(body, source=section_source)
            result.entities_added += r.entities_added
            result.facts_added += r.facts_added
            result.rules_added += r.rules_added
            result.edges_added += r.edges_added
            result.errors.extend(r.errors)
        return result

    def _llm_extract(self, text: str) -> ExtractedTriples | None:
        try:
            import urllib.request
            payload = json.dumps({
                "model": self.llm_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_PROMPT.format(text=text)},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }).encode()
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = json.loads(resp.read())
            content = raw["choices"][0]["message"]["content"]
            return self._parse_llm_output(json.loads(content))
        except Exception:
            return None

    def _parse_llm_output(self, raw: dict[str, Any]) -> ExtractedTriples:
        t = ExtractedTriples()
        for e in raw.get("entities", []):
            t.entities.append(ExtractedEntity(
                name=e.get("name", ""), entity_type=e.get("entity_type", "concept"),
                aliases=e.get("aliases", []), description=e.get("description", ""),
                confidence=float(e.get("confidence", 0.8)),
            ))
        for f in raw.get("facts", []):
            t.facts.append(ExtractedFact(
                text=f.get("text", ""), subject=f.get("subject", "user"),
                predicate=f.get("predicate", "noted"), object=f.get("object"),
                fact_type=f.get("fact_type", "observation"),
                confidence=float(f.get("confidence", 0.8)),
                negated=bool(f.get("negated", False)),
            ))
        for r in raw.get("rules", []):
            t.rules.append(ExtractedRule(
                text=r.get("text", ""), subject=r.get("subject", "user"),
                rule_type=r.get("rule_type", "preference"),
                priority=int(r.get("priority", 50)),
                confidence=float(r.get("confidence", 0.9)),
            ))
        for rel in raw.get("relations", []):
            t.relations.append(ExtractedRelation(
                source=rel.get("source", ""), target=rel.get("target", ""),
                rel_type=rel.get("rel_type", "RELATED_TO"),
                confidence=float(rel.get("confidence", 0.7)),
            ))
        return t

    def _keyword_extract(self, text: str) -> ExtractedTriples:
        t = ExtractedTriples()
        user_added = False
        for line in text.split("\n"):
            stripped = line.strip().lstrip("-•* ")
            if not stripped or HEADER_RE.match(stripped):
                continue
            matched = None
            sl = stripped.lower()
            for marker, (rule_type, priority) in RULE_MARKERS.items():
                if marker.lower() in sl or marker in stripped:
                    matched = (rule_type, priority)
                    break
            if matched:
                rule_type, priority = matched
                t.rules.append(ExtractedRule(
                    text=stripped, subject="user",
                    rule_type=rule_type, priority=priority, confidence=0.95,
                ))
                if not user_added:
                    t.entities.append(ExtractedEntity(name="user", entity_type="person", confidence=1.0))
                    user_added = True
            elif len(stripped) > 10:
                t.facts.append(ExtractedFact(text=stripped, subject="user", confidence=0.5))
                if not user_added:
                    t.entities.append(ExtractedEntity(name="user", entity_type="person", confidence=1.0))
                    user_added = True
        return t

    @staticmethod
    def _canonical_key(entity_type: str, name: str) -> str:
        n = re.sub(r"[^\w가-힣]", "", name.lower().replace(" ", "_"))
        return f"{entity_type}:{n}"

    def _resolve_entity(self, name: str, entity_type: str, aliases: list[str]) -> str:
        canonical = self._canonical_key(entity_type, name)
        if canonical in self._entity_cache:
            return self._entity_cache[canonical]
        # 1. DB exact canonical key
        existing = self.store.find_entity_by_canonical_key(canonical)
        if existing:
            self._entity_cache[canonical] = existing["id"]
            return existing["id"]
        # 2. Alias match
        for alias in [name] + aliases:
            found = self.store.find_entity_by_alias(alias)
            if found:
                self._entity_cache[canonical] = found["id"]
                return found["id"]
        # 3. Create new
        e = Entity(name=name, entity_type=entity_type,
                   aliases=",".join(aliases), confidence=0.8, source="ingest")
        self.store.add_entity(e)
        self._entity_cache[canonical] = e.id
        return e.id

    def _store_triples(self, triples: ExtractedTriples, source: str) -> IngestResult:
        result = IngestResult()
        name_to_id: dict[str, str] = {}

        # Phase 1: entities
        for ent in triples.entities:
            if not ent.name:
                continue
            try:
                eid = self._resolve_entity(ent.name, ent.entity_type, ent.aliases)
                name_to_id[ent.name.lower()] = eid
                result.entities_added += 1
            except Exception as ex:
                result.errors.append(f"entity error: {ex}")

        # Phase 2: facts
        for ef in triples.facts:
            if not ef.text:
                continue
            try:
                f = Fact(
                    text=ef.text, fact_type=ef.fact_type,
                    subject_id=name_to_id.get(ef.subject.lower(), ""),
                    predicate=ef.predicate,
                    object_id=name_to_id.get((ef.object or "").lower(), ""),
                    negated=ef.negated, confidence=ef.confidence,
                    source=source,
                )
                self.store.add_fact(f)
                result.facts_added += 1
                # ABOUT edge if we know the subject entity
                if f.subject_id:
                    self.store.add_about(f.id, f.subject_id)
                    result.edges_added += 1
            except Exception as ex:
                result.errors.append(f"fact error: {ex}")

        # Phase 3: rules
        for er in triples.rules:
            if not er.text:
                continue
            try:
                entity_id = name_to_id.get(er.subject.lower(), "")
                r = Rule(
                    text=er.text, rule_type=er.rule_type, priority=er.priority,
                    confidence=er.confidence, source=source,
                )
                self.store.add_rule(r)
                result.rules_added += 1
                if entity_id:
                    self.store.add_has_rule(entity_id, r.id)
                    result.edges_added += 1
            except Exception as ex:
                result.errors.append(f"rule error: {ex}")

        return result
```

---

## query.py — KnowledgeGraph

```python
from __future__ import annotations
from .schema import GraphStore
from .models import Entity, Fact, Rule
from datetime import datetime, timezone

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
        r = rows[0]
        return {"id": r[0], "name": r[1], "entity_type": r[2], "canonical_key": r[3]}

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
            "facts": [{"id": r[0], "text": r[1], "confidence": r[2], "created_at": r[3]} for r in facts],
            "rules": [{"id": r[0], "text": r[1], "rule_type": r[2], "priority": r[3]} for r in rules],
        }

    def find_contradictions(self) -> list[dict]:
        rows = self.store.query(
            "MATCH (a:Fact)-[:CONTRADICTS]->(b:Fact) "
            "WHERE a.status = 'active' AND b.status = 'active' "
            "RETURN a.id, a.text, b.id, b.text, a.created_at, b.created_at "
            "ORDER BY a.created_at DESC"
        )
        return [{"fact_a": {"id": r[0], "text": r[1], "created_at": r[4]},
                 "fact_b": {"id": r[2], "text": r[3], "created_at": r[5]}} for r in rows]

    def get_causal_chain(self, fact_id: str, depth: int = 3) -> list[dict]:
        rows = self.store.query(
            f"MATCH (s:Fact)-[:CAUSED*1..{depth}]->(e:Fact) "
            f"WHERE s.id = '{fact_id}' AND e.status = 'active' "
            f"RETURN e.id, e.text, e.confidence"
        )
        return [{"id": r[0], "text": r[1], "confidence": r[2]} for r in rows]

    def get_recent_facts(self, limit: int = 20) -> list[dict]:
        rows = self.store.query(
            f"MATCH (f:Fact) WHERE f.status = 'active' "
            f"RETURN f.id, f.text, f.confidence, f.source, f.created_at "
            f"ORDER BY f.created_at DESC LIMIT {limit}"
        )
        return [{"id": r[0], "text": r[1], "confidence": r[2], "source": r[3], "created_at": r[4]}
                for r in rows]

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
        return [{"id": r[0], "text": r[1], "rule_type": r[2], "priority": r[3], "confidence": r[4]}
                for r in rows]

    def export_to_memory_md(self, entity_name: str | None = None) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = [f"# lorien Export ({now})\n"]
        rules = self.get_active_rules()
        if rules:
            lines.append("## Rules\n")
            for r in rules:
                lines.append(f"- [{r['rule_type']}] {r['text']}")
            lines.append("")
        facts = self.get_recent_facts(50)
        if facts:
            lines.append("## Recent Facts\n")
            for f in facts:
                lines.append(f"- {f['text']}")
        contradictions = self.find_contradictions()
        if contradictions:
            lines.append("\n## ⚠️ Contradictions\n")
            for c in contradictions:
                lines.append(f"- \"{c['fact_a']['text']}\" ↔ \"{c['fact_b']['text']}\"")
        return "\n".join(lines) + "\n"
```

---

## cli.py

```python
from __future__ import annotations
import sys
import click
from pathlib import Path
from .schema import GraphStore
from .query import KnowledgeGraph

DEFAULT_DB = "~/.lorien/db"

@click.group()
def main():
    """lorien — local-first personal knowledge graph for AI agents."""

@main.command()
@click.option("--db", default=DEFAULT_DB, show_default=True)
def init(db):
    """Initialize a new lorien graph store."""
    store = GraphStore(db_path=db)
    counts = store.count_nodes()
    click.echo(f"✓ lorien initialized at {Path(db).expanduser()}")
    click.echo(f"  {counts}")

@main.command()
@click.option("--db", default=DEFAULT_DB, show_default=True)
def status(db):
    """Show node counts."""
    store = GraphStore(db_path=db)
    for name, n in store.count_nodes().items():
        click.echo(f"  {name}: {n}")

@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--db", default=DEFAULT_DB, show_default=True)
@click.option("--model", default=None, help="LLM model (enables LLM extraction)")
@click.option("--api-key", default=None, envvar="LORIEN_API_KEY")
@click.option("--base-url", default=None, envvar="LORIEN_LLM_BASE_URL")
def ingest(file, db, model, api_key, base_url):
    """Ingest a text or MEMORY.md file."""
    from .ingest import LorienIngester
    store = GraphStore(db_path=db)
    ingester = LorienIngester(store, llm_model=model, api_key=api_key, base_url=base_url)
    fname = Path(file).name
    if fname.upper().startswith("MEMORY") and file.endswith(".md"):
        result = ingester.ingest_memory_md(file)
    else:
        text = Path(file).read_text(encoding="utf-8")
        result = ingester.ingest_text(text, source=file)
    click.echo(f"✓ {file}: +{result.entities_added} entities, +{result.facts_added} facts, +{result.rules_added} rules")
    if result.errors:
        for e in result.errors[:5]:
            click.echo(f"  ⚠ {e}", err=True)

@main.command()
@click.argument("cypher")
@click.option("--db", default=DEFAULT_DB, show_default=True)
def query(cypher, db):
    """Run raw Cypher query."""
    store = GraphStore(db_path=db)
    for row in store.query(cypher):
        click.echo(row)

@main.command()
@click.argument("entity_name")
@click.option("--db", default=DEFAULT_DB, show_default=True)
def show(entity_name, db):
    """Show all context for an entity."""
    store = GraphStore(db_path=db)
    kg = KnowledgeGraph(store)
    entity = kg.get_entity(entity_name)
    if not entity:
        click.echo(f"Not found: {entity_name}", err=True)
        sys.exit(1)
    ctx = kg.get_entity_context(entity["id"])
    click.echo(f"\n{entity['name']} ({entity['entity_type']})")
    click.echo("─" * 40)
    for f in ctx["facts"]:
        click.echo(f"  • {f['text']}  [{f['confidence']:.2f}]")
    for r in ctx["rules"]:
        click.echo(f"  ★ [{r['rule_type']}] {r['text']}")

@main.command()
@click.option("--to-md", required=True, type=click.Path())
@click.option("--entity", default=None)
@click.option("--db", default=DEFAULT_DB, show_default=True)
def sync(to_md, entity, db):
    """Export graph to MEMORY.md-style file."""
    store = GraphStore(db_path=db)
    kg = KnowledgeGraph(store)
    md = kg.export_to_memory_md(entity_name=entity)
    Path(to_md).write_text(md, encoding="utf-8")
    click.echo(f"✓ Exported to {to_md}")

@main.command()
@click.option("--db", default=DEFAULT_DB, show_default=True)
def contradictions(db):
    """List all detected contradictions."""
    store = GraphStore(db_path=db)
    kg = KnowledgeGraph(store)
    items = kg.find_contradictions()
    if not items:
        click.echo("✓ No contradictions.")
        return
    click.echo(f"⚠️  {len(items)} contradiction(s):")
    for c in items:
        click.echo(f"\n  A: {c['fact_a']['text']}")
        click.echo(f"  B: {c['fact_b']['text']}")
```

---

## tests/conftest.py

```python
import pytest, tempfile, shutil
from lorien.schema import GraphStore

@pytest.fixture
def tmp_store(tmp_path):
    db_path = tmp_path / "test_db"
    store = GraphStore(db_path=str(db_path))
    yield store
```

---

## tests/test_schema.py — 10 tests

Write these test functions using the `tmp_store` fixture:
1. `test_init_creates_tables` — count_nodes() returns {"Entity":0, "Fact":0, "Rule":0}
2. `test_init_is_idempotent` — GraphStore(same path) twice doesn't raise
3. `test_add_entity` — add_entity(Entity("Alice","person")) → query finds it
4. `test_add_fact` — add_fact(Fact("Alice uses Python")) → query finds it
5. `test_add_rule` — add_rule(Rule("절대 React 19 사용 금지", rule_type="prohibition")) → query finds it
6. `test_add_edge_about` — add fact + entity + add_about → MATCH (f)-[:ABOUT]->(e) returns 1 row
7. `test_add_edge_has_rule` — add entity + rule + add_has_rule → MATCH (e)-[:HAS_RULE]->(r) returns 1 row
8. `test_add_edge_contradicts` — add 2 facts + add_contradicts → MATCH (a)-[:CONTRADICTS]->(b) returns 1 row
9. `test_count_nodes` — add 2 entities, 1 fact, 1 rule → count_nodes() returns correct values
10. `test_related_to_with_relation` — add 2 entities + add_related_to(id1, id2, "depends_on") → edge exists

## tests/test_query.py — 10 tests

Use `tmp_store` fixture and KnowledgeGraph wrapper:
1. `test_get_entity_found` — add entity, get_entity(name) returns dict with correct name
2. `test_get_entity_not_found` — get_entity("nonexistent") returns None
3. `test_get_entity_context_facts` — add entity + fact + ABOUT edge → get_entity_context has fact in "facts"
4. `test_get_entity_context_rules` — add entity + rule + HAS_RULE → get_entity_context has rule in "rules"
5. `test_find_contradictions_empty` — no CONTRADICTS edges → returns []
6. `test_find_contradictions` — two facts + CONTRADICTS edge → returns 1 item
7. `test_get_recent_facts` — add 3 facts → get_recent_facts(2) returns 2 items
8. `test_get_active_rules_all` — add 2 rules → get_active_rules() returns 2
9. `test_get_active_rules_by_entity` — add 2 entities with 1 rule each → filter by entity returns 1
10. `test_export_to_memory_md` — add a rule → export_to_memory_md() contains "Rules"

## tests/test_ingest.py — 7 tests

1. `test_keyword_extract_prohibition` — "절대 React 19 사용 금지" → rule with rule_type="prohibition", priority=100
2. `test_keyword_extract_fixed` — "react-grid-layout v1.4.4 고정" → rule with rule_type="fixed"
3. `test_ingest_text_creates_nodes` — ingest_text("Alice is a developer") → entities_added > 0
4. `test_ingest_memory_md` — write a temp MEMORY.md with sections → ingest_memory_md adds nodes
5. `test_entity_resolution_dedup` — ingest "user" twice → only 1 Entity node with name "user"
6. `test_ingest_result_structure` — ingest_text(...) returns IngestResult with int fields
7. `test_ingest_rule_creates_has_rule_edge` — ingest text with "절대" keyword → MATCH (e)-[:HAS_RULE]->(r) exists

---

## Additional instructions

1. Delete all existing .py files in src/lorien/ and tests/ before writing new ones
2. After writing all files, run: `.venv/bin/pip install -e . -q`
3. Then run: `.venv/bin/pytest tests/ -v`
4. Fix any failures. Common issues:
   - Kuzu `show_tables()` may return table type info — adjust `_existing_tables()` if needed
   - Kuzu REL TABLE may not support DEFAULT values — remove DEFAULT from REL TABLE DDL if error
   - String escaping: use `_q()` helper for all string literals in Cypher
5. All 27 tests must pass before finishing.

When all tests pass, run:
openclaw system event --text "Done: lorien 27/27 tests passing" --mode now
