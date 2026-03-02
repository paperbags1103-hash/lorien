# Changelog

All notable changes to `lorien-memory` are documented here.

---

## [0.4.0] — 2026-03-03

### Added

**Epistemic Debt** (`lorien debt`)
- `GraphStore.get_epistemic_debt()` — surfaces facts that are old, high-confidence, and never re-confirmed; sorted by `debt_score = confidence × age_days / 365`
- `LorienMemory.get_epistemic_debt()` — convenience wrapper
- `LorienMemory.review_debt()` — take action: `confirm` / `update` (creates SUPERSEDES edge) / `expire`
- `lorien debt` CLI — tabular display with `--min-confidence`, `--min-age` flags
- `lorien debt --review` — interactive per-fact confirmation loop

**Belief Fork** (`lorien forks`)
- `GraphStore.find_belief_forks()` — detects when different agents hold diverging beliefs about the same subject+predicate
- Severity classification: `critical` (CONTRADICTS edge exists), `warning` (freshness gap > 30 days), `info`
- `LorienMemory.get_belief_forks()` — convenience wrapper with `only_critical` filter
- `lorien forks` CLI — grouped by severity, `--critical-only` flag

**Consequence Simulation** (`lorien simulate`)
- `GraphStore.simulate_decision_impact()` — dry-run impact analysis: compatible facts, needs_update, rule_violations (read-only, never writes)
- `LorienMemory.simulate_decision()` — returns recommendation (`proceed` / `caution` / `reconsider`), impact score, and mandatory disclaimer
- `lorien simulate "<decision>"` CLI — full formatted output with icons

**Common helpers**
- `GraphStore.get_facts_by_subject()` — return all facts for a given subject_id with agent/timestamp metadata

### Tests
- 19 new tests in `tests/test_v04.py` → total **159 tests** (all passing)

---

## [0.3.0] — 2026-03-03

### Added

**Phase 1: Temporal Tagging**
- `last_confirmed`, `expires_at`, `version` fields on `Fact` and `Rule` nodes
- `SUPERSEDES` relationship edge — tracks when a new fact replaces an old one
- `temporal.py` module:
  - `freshness_score(last_confirmed)` — exponential decay score (0.0–1.0, half-life 30 days)
  - `is_stale(last_confirmed, max_age_days, min_confidence, confidence)` — stale detection
  - `classify_temporal_relation(...)` — distinguishes knowledge evolution from contradiction
  - `age_in_days(timestamp)` — utility helper
- `GraphStore` methods: `add_supersedes()`, `confirm_fact()`, `confirm_rule()`, `expire_stale_facts()`, `migrate_v02_to_v03()`
- `LorienMemory` methods: `confirm()`, `get_fact_history()`, `cleanup()`, `freshness()`

**Phase 2: Multi-agent Shared Memory**
- `Agent` node type — tracks name, agent_type, last_active_at
- `agent_id` field on `Fact` and `Rule` — denormalized for fast agent-based filtering
- `CREATED_BY` edge — (Fact) → (Agent) provenance tracking
- `concurrency.py` module: `WriteQueue` — thread-safe serialized write queue for KuzuDB
- `GraphStore` methods: `add_agent()`, `get_or_create_agent()`, `add_created_by()`, `get_agent_stats()`, `list_agents()`
- `LorienMemory` methods: `register_agent()`, `get_agents()`, `get_agent_stats()`, `add_with_agent()`

**Phase 3: Decision Archive**
- `Decision` node type — records what was decided, why, and by whom
- Relationship edges: `BASED_ON` (Decision→Fact), `APPLIED_RULE` (Decision→Rule), `DECIDED_BY` (Decision→Agent), `SUPERSEDES_D` (Decision→Decision)
- `GraphStore` methods: `add_decision()`, `add_based_on()`, `add_applied_rule()`, `add_decided_by()`, `supersede_decision()`, `get_decision_chain()`, `search_decisions()`
- `LorienMemory` methods: `add_decision()`, `why()`, `search_decisions()`, `revoke_decision()`

**Exports**
- `Agent`, `Decision` added to `lorien.__all__`
- `WriteQueue`, `freshness_score`, `is_stale`, `classify_temporal_relation` exported from top-level

### Changed
- `count_nodes()` now includes `Agent` and `Decision` node counts
- `classify_temporal_relation()`: different subject+predicate returns `"unrelated"` (was `"contradiction"`)

### Fixed
- `WriteQueue` race condition between `submit()` and `shutdown()` — now protected by `threading.Lock`
- Cypher injection gaps in `delete()`, `revoke_decision()`, `add_with_agent()` — all now use `_q()` escape
- `_q()` docstring clarifies Unicode escape limitation and recommends parameterized queries for production

### Tests
- 140 tests passing (up from 64 in v0.2.0)
- New test modules: `test_temporal.py` (25), `test_multiagent.py` (22), `test_decisions.py` (21), `test_integration_v03.py` (8)

### Known Limitations (v0.4 TODO)
- `_q()` does not handle Unicode escape sequences (`\u0027`); use parameterized queries for production workloads with untrusted input
- `_uid()` uses 12-hex-char IDs (48-bit); collision risk at very large scale — will be extended to 16+ chars in v0.4
- `get_or_create_agent()` has a TOCTOU race in high-concurrency multi-process scenarios
- `add_with_agent()` agent tagging is post-hoc (after `add()`); failures are silently ignored

---

## [0.2.0] — 2026-03-02

### Added
- **Vector semantic search** (`vectors.py`): `VectorIndex` with SQLite WAL sidecar, `paraphrase-multilingual-MiniLM-L12-v2` embeddings, cosine similarity
- **Contradiction detection** (`contradiction.py`): `ContradictionDetector` — vector similarity → heuristic negation → optional LLM confirm → `CONTRADICTS` edge auto-creation
- **Killer demo** (`demo_killer.py`): shellfish allergy → oyster recommendation → auto-flagged contradiction scenario
- **PyPI packaging**: `hatchling` build backend, package name `lorien-memory`
- **LangChain adapter** (`integrations/langchain.py`): `LorienChatMemory` — `BaseMemory`-compatible
- `ContradictionDetector.from_ingester(ingester)` factory classmethod

### Changed
- README: Mem0 comparison table removed; replaced with single positioning quote
- Contradiction detection threshold: `similarity_threshold=0.55`

### Tests
- 64 tests passing

---

## [0.1.0] — 2026-03-01

### Added
- Initial release: 3-node schema (Entity, Fact, Rule) + 5 edge tables (ABOUT, HAS_RULE, RELATED_TO, CAUSED, CONTRADICTS)
- `GraphStore` (KuzuDB), `LorienIngester` (LLM extraction via OpenClaw gateway), `KnowledgeGraph` (query layer)
- `LorienMemory`: Mem0-compatible API (`add`, `search`, `get_all`, `delete`, `get_entity_rules`, `get_contradictions`)
- `lorien serve`: local web graph visualization (stdlib + vis.js CDN)
- CLI: `init`, `status`, `ingest`, `query`, `show`, `contradictions`, `memory`, `serve`
- OpenClaw gateway auto-detection
- MEMORY.md LLM ingest support
- 43 tests passing
