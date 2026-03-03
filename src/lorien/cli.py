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
@click.argument("text")
@click.option("--db", default=DEFAULT_DB, show_default=True)
@click.option("--confidence", default=0.8, show_default=True, help="Confidence 0.0–1.0")
@click.option("--subject", default=None, help="Entity name this fact belongs to")
def add(text: str, db: str, confidence: float, subject: str | None) -> None:
    """Add a single fact directly to the graph.

    Example:
      lorien add "Alice는 굴 알레르기가 있다" --confidence 0.9
      lorien add "사용자는 커피를 좋아한다" --subject 사용자
    """
    from .schema import GraphStore

    store = GraphStore(db_path=db)
    entity_name = subject or _extract_subject(text)
    entity = store.get_or_create_entity(entity_name, "person")
    fact_id = store.add_fact(text, entity["id"], confidence=confidence)
    click.echo(f"✓ Added fact [{confidence:.2f}]: {text}")
    # Check for contradictions
    contras = store.get_contradictions()
    relevant = [c for c in contras if fact_id in (c.get("fact_a"), c.get("fact_b"))]
    if relevant:
        click.echo(f"⚡ {len(relevant)} contradiction(s) detected!")
        for c in relevant:
            click.echo(f"  ↔ {c.get('fact_a_text', '')} vs {c.get('fact_b_text', '')}")


def _extract_subject(text: str) -> str:
    """Naive subject extraction — first word or 'user'."""
    words = text.split()
    if words:
        return words[0].rstrip("는은이가")
    return "user"


@main.command()
@click.argument("file", type=click.Path(exists=True, allow_dash=True))
@click.option("--db", default=DEFAULT_DB, show_default=True)
@click.option("--model", default=None, help="LLM model e.g. claude-haiku-3-5 (enables LLM extraction)")
@click.option("--api-key", default=None, envvar=["ANTHROPIC_API_KEY", "LORIEN_API_KEY"],
              help="API key (reads ANTHROPIC_API_KEY or LORIEN_API_KEY from env)")
@click.option("--base-url", default=None, envvar="LORIEN_LLM_BASE_URL")
@click.option("--verbose", "-v", is_flag=True, default=False)
@click.option("--batch", default=1, show_default=True,
              help="Sections per LLM call (>1 reduces API calls, use 3-5)")
def ingest(
    file: str, db: str, model: str | None, api_key: str | None,
    base_url: str | None, verbose: bool, batch: int
) -> None:
    """Ingest a text or MEMORY.md file.

    With --model: uses LLM for rich entity extraction.
    Without --model: keyword fallback (rules only).

    Example:
      lorien ingest MEMORY.md --model haiku --batch 4
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

    # Auto-route: stdin(-), .md files, others
    if file == "-":
        text = sys.stdin.read()
        result = ingester.ingest_text(text, source="stdin")
    elif Path(file).suffix.lower() == ".md":
        result = ingester.ingest_memory_md(file, verbose=verbose, batch_size=batch)
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
@click.argument("user_id")
@click.option("--db", default=DEFAULT_DB, show_default=True)
@click.option("--model", default=None, help="LLM model for extraction")
@click.option("--api-key", default=None, envvar=["ANTHROPIC_API_KEY", "LORIEN_API_KEY"])
@click.option("--limit", default=20, show_default=True)
def memory(user_id: str, db: str, model: str | None, api_key: str | None, limit: int) -> None:
    """Show all memories for USER_ID, or pipe a conversation for real-time ingestion.

    Show memories:
      lorien memory 아부지

    Add from stdin (JSON messages):
      echo '[{"role":"user","content":"나는 커피를 싫어해"}]' | lorien memory 아부지 --model haiku
    """
    import select

    from .memory import LorienMemory

    mem = LorienMemory(db_path=db, model=model, api_key=api_key)

    # Check if stdin has data (piped input)
    if select.select([sys.stdin], [], [], 0.0)[0]:
        import json as _json
        raw = sys.stdin.read().strip()
        try:
            messages = _json.loads(raw)
        except Exception:
            click.echo("⚠ stdin must be JSON array of {role, content} objects", err=True)
            sys.exit(1)
        result = mem.add(messages, user_id=user_id)
        click.echo(f"✓ +{result['entities']} entities, +{result['facts']} facts, +{result['rules']} rules")
    else:
        # Show all memories
        memories = mem.get_all(user_id=user_id, limit=limit)
        if not memories:
            click.echo(f"No memories for {user_id}")
            return
        click.echo(f"\n{user_id} — {len(memories)} memories")
        click.echo("─" * 40)
        for m in memories:
            prefix = "★" if m["type"] == "rule" else "•"
            extra = f" [p{m.get('priority', '')}]" if m["type"] == "rule" else f" [{m['score']:.2f}]"
            click.echo(f"  {prefix} {m['memory']}{extra}")


@main.command()
@click.option("--db", default=DEFAULT_DB, show_default=True)
@click.option("--port", default=7331, show_default=True)
def serve(db: str, port: int) -> None:
    """Launch local web graph viewer at http://127.0.0.1:PORT."""
    from .serve import serve as _serve
    _serve(db_path=db, port=port)


@main.command()
@click.option("--db", default=DEFAULT_DB, show_default=True)
@click.option("--min-confidence", default=0.7, show_default=True, help="Min confidence threshold")
@click.option("--min-age", default=60.0, show_default=True, help="Min age in days")
@click.option("--review", is_flag=True, help="Interactive review mode")
def debt(db: str, min_confidence: float, min_age: float, review: bool) -> None:
    """Show epistemic debt — facts assumed without re-verification."""
    from .memory import LorienMemory
    mem = LorienMemory(db_path=db, enable_vectors=False)
    items = mem.get_epistemic_debt(
        min_confidence=min_confidence,
        min_age_days=min_age,
    )
    if not items:
        click.echo("✓ No epistemic debt found.")
        return

    click.echo(f"\n📋 Epistemic Debt — {len(items)} unverified high-confidence facts\n")
    click.echo(f"  {'score':>6}  {'age':>8}  {'conf':>5}  fact")
    click.echo("  " + "─" * 68)
    for item in items:
        subj = f"[{item['subject_name']}] " if item['subject_name'] else ""
        click.echo(
            f"  {item['debt_score']:>6.2f}  "
            f"{item['age_days']:>5.0f}d  "
            f"{item['confidence']:>5.2f}  "
            f"{subj}{item['fact_text'][:60]}"
        )

    if review:
        click.echo("\n─── Interactive Review ───\n")
        for item in items:
            click.echo(f"❓ \"{item['fact_text']}\"")
            click.echo(f"   Age: {item['age_days']:.0f} days  Confidence: {item['confidence']:.2f}")
            choice = click.prompt("   [c]onfirm / [u]pdate / [e]xpire / [s]kip", default="s")
            if choice == "c":
                mem.review_debt(item["fact_id"], "confirm")
                click.echo("   ✓ Confirmed. Freshness reset.")
            elif choice == "u":
                new_text = click.prompt("   New value")
                result = mem.review_debt(item["fact_id"], "update", new_text=new_text)
                click.echo(f"   ✓ Updated → new fact id: {result['new_fact_id']}")
            elif choice == "e":
                mem.review_debt(item["fact_id"], "expire")
                click.echo("   ✓ Expired.")
            else:
                click.echo("   → Skipped.")
    else:
        click.echo(f"\n  Run 'lorien debt --review' for interactive confirmation.")


@main.command()
@click.option("--db", default=DEFAULT_DB, show_default=True)
@click.option("--critical-only", is_flag=True, help="Show only CRITICAL forks")
def forks(db: str, critical_only: bool) -> None:
    """Show belief forks — where different agents hold diverging views."""
    from .memory import LorienMemory
    mem = LorienMemory(db_path=db, enable_vectors=False)
    items = mem.get_belief_forks(only_critical=critical_only)

    if not items:
        click.echo("✓ No belief forks detected.")
        return

    severity_icon = {"critical": "⛔", "warning": "⚠️ ", "info": "ℹ️ "}
    by_severity: dict = {"critical": [], "warning": [], "info": []}
    for item in items:
        by_severity[item["severity"]].append(item)

    click.echo(f"\n🔀 Belief Forks — {len(items)} detected\n")
    for severity in ("critical", "warning", "info"):
        group = by_severity[severity]
        if not group:
            continue
        icon = severity_icon[severity]
        click.echo(f"{icon} {severity.upper()} ({len(group)})")
        for fork in group:
            click.echo(f"  Subject: {fork['subject_name']} / predicate: {fork['predicate']}")
            for f in fork["forks"]:
                age = f"{fork['days_since_oldest']:.0f}d" if fork['days_since_oldest'] else "?"
                click.echo(
                    f"    ├─ [{f['agent_id']}]  "
                    f"conf:{f['confidence']:.2f}  "
                    f"\"{f['fact_text'][:50]}\""
                )
            click.echo("")


@main.command()
@click.argument("decision_text")
@click.option("--db", default=DEFAULT_DB, show_default=True)
def simulate(decision_text: str, db: str) -> None:
    """Simulate adding a decision — see impact before committing."""
    from .memory import LorienMemory
    mem = LorienMemory(db_path=db, enable_vectors=False)

    click.echo(f"\n🔮 Simulation: \"{decision_text}\"\n")
    click.echo("Analyzing graph...")

    result = mem.simulate_decision(decision_text)

    click.echo(f"\n✅ Compatible: {result['compatible_facts']} facts")

    if result["needs_update"]:
        click.echo(f"⚠️  Needs review ({len(result['needs_update'])}):")
        for item in result["needs_update"]:
            click.echo(f"    - {item['text'][:60]}")

    if result["rule_violations"]:
        click.echo(f"❌ Rule violations ({len(result['rule_violations'])}):")
        for r in result["rule_violations"]:
            click.echo(f"    - [priority: {r['priority']}] {r['text'][:60]}")

    rec_icon = {"proceed": "✅", "caution": "⚠️ ", "reconsider": "❌"}
    icon = rec_icon.get(result["recommendation"], "?")
    click.echo(f"\nImpact score: {result['impact_score']:.2f}")
    click.echo(f"Recommendation: {icon} {result['recommendation'].upper()}")
    click.echo(f"\n⚠️  {result['disclaimer']}")


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
