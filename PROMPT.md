# lorien — Personal Knowledge Graph for AI Agents

Build a Python library called `lorien` — a personal knowledge graph backed by Kuzu embedded graph DB.

## Project Structure

```
lorien/
├── pyproject.toml
├── README.md
├── src/
│   └── lorien/
│       ├── __init__.py
│       ├── models.py       # dataclasses for nodes/edges
│       ├── schema.py       # Kuzu schema + GraphStore class
│       ├── ingest.py       # natural language → graph nodes/edges
│       ├── query.py        # query interface (Cypher + convenience methods)
│       └── cli.py          # CLI (click)
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── test_schema.py      # basic CRUD tests
```

## pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "lorien"
version = "0.1.0"
description = "Personal knowledge graph for AI agents — backed by Kuzu embedded graph DB"
requires-python = ">=3.12"
dependencies = [
    "kuzu>=0.8.0",
    "click>=8.0",
    "gitpython>=3.1",
]

[project.optional-dependencies]
llm = ["openai>=1.0"]

[project.scripts]
lorien = "lorien.cli:main"
```

## models.py — Python dataclasses

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Person:
    id: str
    name: str
    aliases: str = ""
    notes: str = ""

@dataclass
class Organization:
    id: str
    name: str
    org_type: str = ""  # company, team, school, etc.

@dataclass
class Project:
    id: str
    name: str
    status: str = "active"  # active, completed, abandoned
    domain: str = ""

@dataclass
class Goal:
    id: str
    text: str
    status: str = "active"  # active, achieved, abandoned
    created_at: str = ""

@dataclass
class Preference:
    id: str
    text: str
    domain: str = ""  # finance, work, lifestyle, etc.
    strength: str = "strong"  # strong, moderate, weak

@dataclass
class Event:
    id: str
    text: str
    occurred_at: str = ""

@dataclass
class Concept:
    id: str
    text: str
    domain: str = ""
```

## schema.py — GraphStore

Use Kuzu 0.8.x API (kuzu.Database(path), kuzu.Connection(db)).

Node tables:
```cypher
CREATE NODE TABLE IF NOT EXISTS Person(id STRING, name STRING, aliases STRING, notes STRING, PRIMARY KEY(id))
CREATE NODE TABLE IF NOT EXISTS Organization(id STRING, name STRING, org_type STRING, PRIMARY KEY(id))
CREATE NODE TABLE IF NOT EXISTS Project(id STRING, name STRING, status STRING, domain STRING, PRIMARY KEY(id))
CREATE NODE TABLE IF NOT EXISTS Goal(id STRING, text STRING, status STRING, created_at STRING, PRIMARY KEY(id))
CREATE NODE TABLE IF NOT EXISTS Preference(id STRING, text STRING, domain STRING, strength STRING, PRIMARY KEY(id))
CREATE NODE TABLE IF NOT EXISTS Event(id STRING, text STRING, occurred_at STRING, PRIMARY KEY(id))
CREATE NODE TABLE IF NOT EXISTS Concept(id STRING, text STRING, domain STRING, PRIMARY KEY(id))
```

Edge tables (use REL TABLE syntax for Kuzu):
```cypher
CREATE REL TABLE IF NOT EXISTS KNOWS(FROM Person TO Person, since STRING, context STRING)
CREATE REL TABLE IF NOT EXISTS WORKS_AT(FROM Person TO Organization, role STRING, since STRING)
CREATE REL TABLE IF NOT EXISTS HAS_GOAL(FROM Person TO Goal)
CREATE REL TABLE IF NOT EXISTS HAS_PREFERENCE(FROM Person TO Preference)
CREATE REL TABLE IF NOT EXISTS INVOLVED_IN(FROM Person TO Project, role STRING)
CREATE REL TABLE IF NOT EXISTS CAUSED(FROM Event TO Event, description STRING)
CREATE REL TABLE IF NOT EXISTS CONTRADICTS(FROM Goal TO Goal, reason STRING)
CREATE REL TABLE IF NOT EXISTS RELATED_TO(FROM Person TO Concept, rel_type STRING, notes STRING)
```

GraphStore class:
- `__init__(self, db_path: str = ".lorien/db")` — opens/creates Kuzu DB
- `add_person(person: Person) -> None`
- `add_organization(org: Organization) -> None`
- `add_project(project: Project) -> None`
- `add_goal(goal: Goal) -> None`
- `add_preference(pref: Preference) -> None`
- `add_event(event: Event) -> None`
- `add_concept(concept: Concept) -> None`
- `add_knows(from_id: str, to_id: str, since: str = "", context: str = "") -> None`
- `add_works_at(person_id: str, org_id: str, role: str = "", since: str = "") -> None`
- `add_has_goal(person_id: str, goal_id: str) -> None`
- `add_has_preference(person_id: str, pref_id: str) -> None`
- `add_involved_in(person_id: str, project_id: str, role: str = "") -> None`
- `add_caused(from_event_id: str, to_event_id: str, description: str = "") -> None`
- `add_contradicts(goal_id_1: str, goal_id_2: str, reason: str = "") -> None`
- `add_related_to(person_id: str, concept_id: str, rel_type: str = "", notes: str = "") -> None`
- `query(cypher: str) -> list[list]` — execute raw Cypher, return rows as list of lists
- `count_nodes() -> dict[str, int]` — return {"Person": N, "Goal": M, ...}

Important: Use `_rows()` helper that uses `has_next()` / `get_next()` pattern (NOT `get_as_df()` — avoids numpy dependency):
```python
def _rows(self, cypher: str) -> list:
    result = self.conn.execute(cypher)
    rows = []
    while result.has_next():
        rows.append(result.get_next())
    return rows
```

String escaping in Kupher: use `\'` not `''`. Backslashes must be double-escaped first. Helper:
```python
def _quote(self, s: str) -> str:
    s = s.replace("\\", "\\\\")
    s = s.replace("'", "\\'")
    return f"'{s}'"
```

## ingest.py — Natural language ingestion

Class `TextIngester`:
- `__init__(self, store: GraphStore)`
- `ingest_text(self, text: str, source: str = "") -> list[str]` — parse text, extract entities, add to graph, return list of what was added
- Keyword-based extraction (no LLM required):
  - Lines matching `[Name] (is|are|works at|joined)` → Person/Organization
  - Lines with `목표:` or `Goal:` → Goal node
  - Lines with `선호:` or `Preference:` → Preference node
  - Lines with ISO dates → Event node
- Optional LLM extraction: if `LORIEN_LLM_MODEL` env var is set, use OpenAI-compatible API (`LORIEN_LLM_BASE_URL`, `LORIEN_API_KEY`) for richer extraction
- `ingest_memory_md(self, path: str) -> list[str]` — read a MEMORY.md-style markdown file, extract and store

## query.py — Query interface

Class `KnowledgeGraph`:
- `__init__(self, store: GraphStore)`
- `find_person(self, name: str) -> Optional[dict]`
- `get_goals(self, person_id: str) -> list[dict]`
- `get_preferences(self, person_id: str) -> list[dict]`
- `find_contradictions(self) -> list[dict]` — return all CONTRADICTS edges
- `get_context(self, person_id: str) -> dict` — return all connected info about a person (goals, prefs, org, projects)
- `raw(self, cypher: str) -> list[list]` — raw Cypher query

## cli.py — CLI commands

Using click:
- `lorien init [--db PATH]` — initialize empty graph store
- `lorien status` — show node counts per type
- `lorien add person NAME [--notes TEXT]`
- `lorien add goal PERSON_ID TEXT [--domain DOMAIN]`
- `lorien add preference PERSON_ID TEXT [--domain DOMAIN]`
- `lorien ingest FILE` — ingest a text/markdown file
- `lorien query CYPHER` — run raw Cypher query, print results
- `lorien show person NAME` — show all context for a person

## tests/test_schema.py

Write tests that:
1. Create a temp GraphStore in /tmp/lorien-test/
2. Add a Person
3. Add an Organization
4. Add WORKS_AT edge
5. Add a Goal
6. Add HAS_GOAL edge
7. Query back and verify
8. Test count_nodes()
9. Test find_contradictions() with two contradicting goals

Use pytest. Tests should NOT require internet or LLM.

## Additional notes

- Python 3.12+, Kuzu 0.8.x (already in venv)
- No numpy dependency (use has_next/get_next pattern)
- All IDs: use `slugify(name)` or `str(uuid4())[:8]` 
- Type hints everywhere
- Docstrings on public methods
- After implementation, run: `pip install -e .` in the venv and `pytest tests/ -v`

When completely finished, run:
openclaw system event --text "Done: lorien knowledge graph scaffold complete" --mode now
