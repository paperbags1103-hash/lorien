from lorien.models import Entity, Fact, Rule
from lorien.schema import GraphStore


def test_init_creates_tables(tmp_store):
    assert tmp_store.count_nodes() == {"Entity": 0, "Fact": 0, "Rule": 0}


def test_init_is_idempotent(tmp_path):
    db_path = tmp_path / "graph"
    GraphStore(str(db_path))
    GraphStore(str(db_path))


def test_add_entity(tmp_store):
    entity = Entity("Alice", "person")
    tmp_store.add_entity(entity)

    rows = tmp_store.query("MATCH (e:Entity) RETURN e.name")
    assert rows == [["Alice"]]


def test_add_fact(tmp_store):
    fact = Fact("Alice uses Python")
    tmp_store.add_fact(fact)

    rows = tmp_store.query("MATCH (f:Fact) RETURN f.text")
    assert rows == [["Alice uses Python"]]


def test_add_rule(tmp_store):
    rule = Rule("절대 React 19 사용 금지", rule_type="prohibition")
    tmp_store.add_rule(rule)

    rows = tmp_store.query("MATCH (r:Rule) RETURN r.text, r.rule_type")
    assert rows == [["절대 React 19 사용 금지", "prohibition"]]


def test_add_edge_about(tmp_store):
    entity = Entity("Alice", "person")
    fact = Fact("Alice uses Python")
    tmp_store.add_entity(entity)
    tmp_store.add_fact(fact)
    tmp_store.add_about(fact.id, entity.id)

    rows = tmp_store.query("MATCH (f:Fact)-[:ABOUT]->(e:Entity) RETURN count(*)")
    assert rows == [[1]]


def test_add_edge_has_rule(tmp_store):
    entity = Entity("Alice", "person")
    rule = Rule("Always use tests", rule_type="fixed")
    tmp_store.add_entity(entity)
    tmp_store.add_rule(rule)
    tmp_store.add_has_rule(entity.id, rule.id)

    rows = tmp_store.query("MATCH (e:Entity)-[:HAS_RULE]->(r:Rule) RETURN count(*)")
    assert rows == [[1]]


def test_add_edge_contradicts(tmp_store):
    fact_a = Fact("Alice likes tea")
    fact_b = Fact("Alice dislikes tea")
    tmp_store.add_fact(fact_a)
    tmp_store.add_fact(fact_b)
    tmp_store.add_contradicts(fact_a.id, fact_b.id)

    rows = tmp_store.query("MATCH (a:Fact)-[:CONTRADICTS]->(b:Fact) RETURN count(*)")
    assert rows == [[1]]


def test_count_nodes(tmp_store):
    tmp_store.add_entity(Entity("Alice", "person"))
    tmp_store.add_entity(Entity("Bob", "person"))
    tmp_store.add_fact(Fact("Alice uses Python"))
    tmp_store.add_rule(Rule("Always write tests"))

    assert tmp_store.count_nodes() == {"Entity": 2, "Fact": 1, "Rule": 1}


def test_related_to_with_relation(tmp_store):
    first = Entity("Backend", "project")
    second = Entity("Database", "tool")
    tmp_store.add_entity(first)
    tmp_store.add_entity(second)
    tmp_store.add_related_to(first.id, second.id, "depends_on")

    rows = tmp_store.query("MATCH (a:Entity)-[r:RELATED_TO]->(b:Entity) RETURN r.relation")
    assert rows == [["depends_on"]]
