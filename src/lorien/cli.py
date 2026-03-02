from __future__ import annotations

import sys
from pathlib import Path

import click

from .query import KnowledgeGraph
from .schema import GraphStore

DEFAULT_DB = "~/.lorien/db"


@click.group()
def main() -> None:
    """lorien — local-first personal knowledge graph for AI agents."""


@main.command()
@click.option("--db", default=DEFAULT_DB, show_default=True)
def init(db: str) -> None:
    """Initialize a new lorien graph store."""
    store = GraphStore(db_path=db)
    counts = store.count_nodes()
    click.echo(f"✓ lorien initialized at {Path(db).expanduser()}")
    click.echo(f"  {counts}")


@main.command()
@click.option("--db", default=DEFAULT_DB, show_default=True)
def status(db: str) -> None:
    """Show node counts."""
    store = GraphStore(db_path=db)
    for name, count in store.count_nodes().items():
        click.echo(f"  {name}: {count}")


@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--db", default=DEFAULT_DB, show_default=True)
@click.option("--model", default=None, help="LLM model e.g. claude-haiku-3-5 (enables LLM extraction)")
@click.option("--api-key", default=None, envvar=["ANTHROPIC_API_KEY", "LORIEN_API_KEY"],
              help="API key (reads ANTHROPIC_API_KEY or LORIEN_API_KEY from env)")
@click.option("--base-url", default=None, envvar="LORIEN_LLM_BASE_URL")
@click.option("--verbose", "-v", is_flag=True, default=False)
def ingest(
    file: str, db: str, model: str | None, api_key: str | None,
    base_url: str | None, verbose: bool
) -> None:
    """Ingest a text or MEMORY.md file.

    With --model: uses LLM for rich entity extraction.
    Without --model: keyword fallback (rules only).

    Example:
      lorien ingest MEMORY.md --model claude-haiku-3-5
    """
    from .ingest import LorienIngester

    # Let LorienIngester auto-detect OpenClaw gateway; only fail if explicitly needed
    if model and not api_key:
        from .ingest import _read_openclaw_gateway
        if not _read_openclaw_gateway():
            click.echo("⚠ --model set but no API key found (set ANTHROPIC_API_KEY or configure OpenClaw gateway)", err=True)
            sys.exit(1)
        if verbose:
            click.echo("→ Using OpenClaw gateway")

    store = GraphStore(db_path=db)
    ingester = LorienIngester(store, llm_model=model, api_key=api_key, base_url=base_url)

    if verbose and model:
        click.echo(f"→ LLM mode: {model}")

    filename = Path(file).name
    if filename.upper().startswith("MEMORY") and file.endswith(".md"):
        result = ingester.ingest_memory_md(file, verbose=verbose)
    else:
        text = Path(file).read_text(encoding="utf-8")
        result = ingester.ingest_text(text, source=file)

    click.echo(
        f"✓ {file}: +{result.entities_added} entities, +{result.facts_added} facts, +{result.rules_added} rules"
    )
    if result.errors:
        for error in result.errors[:5]:
            click.echo(f"  ⚠ {error}", err=True)


@main.command()
@click.argument("cypher")
@click.option("--db", default=DEFAULT_DB, show_default=True)
def query(cypher: str, db: str) -> None:
    """Run raw Cypher query."""
    store = GraphStore(db_path=db)
    for row in store.query(cypher):
        click.echo(row)


@main.command()
@click.argument("entity_name")
@click.option("--db", default=DEFAULT_DB, show_default=True)
def show(entity_name: str, db: str) -> None:
    """Show all context for an entity."""
    store = GraphStore(db_path=db)
    graph = KnowledgeGraph(store)
    entity = graph.get_entity(entity_name)
    if not entity:
        click.echo(f"Not found: {entity_name}", err=True)
        sys.exit(1)
    context = graph.get_entity_context(entity["id"])
    click.echo(f"\n{entity['name']} ({entity['entity_type']})")
    click.echo("─" * 40)
    for fact in context["facts"]:
        click.echo(f"  • {fact['text']}  [{fact['confidence']:.2f}]")
    for rule in context["rules"]:
        click.echo(f"  ★ [{rule['rule_type']}] {rule['text']}")


@main.command()
@click.option("--to-md", required=True, type=click.Path())
@click.option("--entity", default=None)
@click.option("--db", default=DEFAULT_DB, show_default=True)
def sync(to_md: str, entity: str | None, db: str) -> None:
    """Export graph to MEMORY.md-style file."""
    store = GraphStore(db_path=db)
    graph = KnowledgeGraph(store)
    markdown = graph.export_to_memory_md(entity_name=entity)
    Path(to_md).write_text(markdown, encoding="utf-8")
    click.echo(f"✓ Exported to {to_md}")


@main.command()
@click.option("--db", default=DEFAULT_DB, show_default=True)
def contradictions(db: str) -> None:
    """List all detected contradictions."""
    store = GraphStore(db_path=db)
    graph = KnowledgeGraph(store)
    items = graph.find_contradictions()
    if not items:
        click.echo("✓ No contradictions.")
        return
    click.echo(f"⚠️  {len(items)} contradiction(s):")
    for item in items:
        click.echo(f"\n  A: {item['fact_a']['text']}")
        click.echo(f"  B: {item['fact_b']['text']}")
