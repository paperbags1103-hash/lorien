from lorien.ingest import IngestResult, LorienIngester


def test_keyword_extract_prohibition(tmp_store):
    ingester = LorienIngester(tmp_store)

    triples = ingester._keyword_extract("절대 React 19 사용 금지")

    assert len(triples.rules) == 1
    assert triples.rules[0].rule_type == "prohibition"
    assert triples.rules[0].priority == 100


def test_keyword_extract_fixed(tmp_store):
    ingester = LorienIngester(tmp_store)

    triples = ingester._keyword_extract("react-grid-layout v1.4.4 고정")

    assert len(triples.rules) == 1
    assert triples.rules[0].rule_type == "fixed"


def test_ingest_text_creates_nodes(tmp_store):
    ingester = LorienIngester(tmp_store)

    result = ingester.ingest_text("Alice is a developer")

    assert result.entities_added > 0


def test_ingest_memory_md(tmp_store, tmp_path):
    memory = tmp_path / "MEMORY.md"
    memory.write_text("# Rules\n절대 React 19 사용 금지\n\n# Notes\nAlice is a developer\n", encoding="utf-8")
    ingester = LorienIngester(tmp_store)

    result = ingester.ingest_memory_md(str(memory))

    assert result.entities_added > 0
    assert result.rules_added > 0 or result.facts_added > 0


def test_entity_resolution_dedup(tmp_store):
    ingester = LorienIngester(tmp_store)

    ingester.ingest_text("user likes tests")
    ingester.ingest_text("user writes Python")
    rows = tmp_store.query("MATCH (e:Entity) WHERE e.name = 'user' RETURN count(e)")

    assert rows == [[1]]


def test_ingest_result_structure(tmp_store):
    ingester = LorienIngester(tmp_store)

    result = ingester.ingest_text("Alice is a developer")

    assert isinstance(result, IngestResult)
    assert isinstance(result.entities_added, int)
    assert isinstance(result.facts_added, int)
    assert isinstance(result.rules_added, int)
    assert isinstance(result.edges_added, int)


def test_ingest_rule_creates_has_rule_edge(tmp_store):
    ingester = LorienIngester(tmp_store)

    ingester.ingest_text("절대 React 19 사용 금지")
    rows = tmp_store.query("MATCH (e:Entity)-[:HAS_RULE]->(r:Rule) RETURN count(*)")

    assert rows == [[1]]
