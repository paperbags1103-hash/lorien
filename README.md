# lorien

`lorien` is a small Python library for maintaining a personal knowledge graph for AI agents on top of an embedded Kuzu database.

## Features

- Typed node models for people, organizations, projects, goals, preferences, events, and concepts
- Embedded graph store with a Kuzu schema and CRUD helpers
- Simple text ingestion for `Goal:`, `Preference:`, Korean equivalents, and dated events
- Convenience query interface for person context and contradiction lookup
- Click-based CLI for initialization, ingest, querying, and inspection

## Install

```bash
pip install -e .
```

## CLI

```bash
lorien init
lorien add person "Ada Lovelace" --notes "Analytical engine pioneer"
lorien add goal ada-lovelace "Finish graph prototype"
lorien status
lorien show person "Ada Lovelace"
```

## Development

```bash
pytest tests/ -v
```
