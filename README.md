# 🌳 lorien

**Local-first personal knowledge graph for AI agents.**  
What to believe, why, and what conflicts — structured memory that Mem0 can't do.

```bash
pip install lorien-memory           # core (KuzuDB + CLI)
pip install "lorien-memory[vectors]"  # + semantic search
```

---

## Why lorien?

> *"Other tools tell you what the user said. lorien tells you what to believe, why, and what conflicts."*

lorien stores *structured knowledge* — not just flat strings. Every fact has a source, every rule has a priority, and contradictions are detected automatically. Local, free, no server required.

---

## Quickstart

```python
from lorien import LorienMemory

mem = LorienMemory(enable_vectors=True)

# Add a conversation
mem.add([
    {"role": "user",      "content": "I have a severe shellfish allergy. Oysters send me to the ER."},
    {"role": "assistant", "content": "Noted — I'll never recommend shellfish."},
], user_id="alice")

# 3 months later — new conversation
mem.add([
    {"role": "user",      "content": "Where should I eat tonight?"},
    {"role": "assistant", "content": "The new oyster bar on Main St is great!"},
], user_id="alice")

# Semantic search — finds allergy even without exact keywords
results = mem.search("seafood restrictions", user_id="alice")
# → [{"memory": "User has severe shellfish allergy...", "score": 0.82}]

# Auto-detected contradiction
contradictions = mem.get_contradictions()
# → [{"fact_a": "shellfish allergy...", "fact_b": "oyster bar recommendation..."}]

# Hard rules with priority
rules = mem.get_entity_rules("alice")
# → [{"text": "Never recommend shellfish to alice", "priority": 100}]
```

---

## Schema

lorien uses [KuzuDB](https://kuzudb.com) — an embedded graph database (like SQLite, but for graphs).

```
Entity ─── HAS_RULE ───► Rule
  │
ABOUT
  │
  ▼
Fact ─── CAUSED ──► Fact
  │
CONTRADICTS
  │
  ▼
Fact
```

**3 node types:**
- **Entity** — people, organizations, topics (`canonical_key = "type:name"`)
- **Fact** — statements about entities (subject → predicate → object)
- **Rule** — constraints with priority 0–100 (100 = absolute prohibition)

**5 edge types:** `ABOUT`, `HAS_RULE`, `RELATED_TO`, `CAUSED`, `CONTRADICTS`

---

## CLI

```bash
# Initialize
lorien init

# Check status
lorien status

# Ingest a file (MEMORY.md, notes, etc.)
lorien ingest MEMORY.md
lorien ingest MEMORY.md --model haiku   # LLM extraction via OpenClaw

# Query the graph
lorien query "MATCH (e:Entity) RETURN e.name LIMIT 10"

# Show entity details
lorien show "alice"

# List contradictions
lorien contradictions

# Conversation memory for a user
lorien memory alice

# Web visualization (vis.js, no extra deps)
lorien serve
```

---

## Contradiction Detection

After every fact is ingested, lorien automatically checks for semantic contradictions:

1. **Vector similarity** — find facts with similar meaning (threshold 0.55)
2. **Heuristic check** — negation pair patterns (허용↔금지, always↔never, must↔must not, ...)
3. **LLM confirmation** *(optional)* — yes/no question to any OpenAI-compatible model
4. **CONTRADICTS edge** — auto-created in the graph for later querying

```python
detector = ContradictionDetector(
    store=store,
    vector_index=vi,
    llm_model="gpt-4o-mini",
    api_key="sk-...",
    similarity_threshold=0.55,
)
n = detector.check_and_record(new_fact_id, new_fact_text)
```

---

## OpenClaw Integration

lorien auto-detects the [OpenClaw](https://github.com/openclaw/openclaw) gateway when available:

```bash
lorien ingest MEMORY.md --model haiku   # routes through OpenClaw → Anthropic
lorien ingest notes.md  --model flash   # routes through OpenClaw → Gemini
```

No API key needed when OpenClaw gateway is running locally.

---

## Installation

```bash
# Core only (graph + CLI, no LLM, no vectors)
pip install lorien-memory

# With semantic search
pip install "lorien-memory[vectors]"

# With OpenAI-compatible LLM extraction
pip install "lorien-memory[llm]"

# Everything
pip install "lorien-memory[all]"
```

**Requirements:** Python 3.12+, no server, no Docker.  
DB stored at `~/.lorien/db`. Vectors at `~/.lorien/vectors.db`.

---

## Roadmap

- [x] v0.1 — Core graph schema (Entity, Fact, Rule + 5 edge types)
- [x] v0.1 — LLM ingest via OpenClaw gateway
- [x] v0.1 — Mem0-compatible `LorienMemory` API
- [x] v0.2 — Vector semantic search (sentence-transformers, multilingual)
- [x] v0.2 — Automatic contradiction detection
- [ ] v0.2 — PyPI release (`pip install lorien-memory`)
- [ ] v1.0 — Web graph visualization
- [ ] v1.0 — LangChain adapter

---

---

MIT License · [GitHub](https://github.com/paperbags1103-hash/lorien)
