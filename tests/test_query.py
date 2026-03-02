from lorien.models import Entity, Fact, Rule
from lorien.query import KnowledgeGraph


def test_get_entity_found(tmp_store):
    tmp_store.add_entity(Entity("Alice", "person"))
    graph = KnowledgeGraph(tmp_store)

    entity = graph.get_entity("Alice")

    assert entity is not None
    assert entity["name"] == "Alice"


def test_get_entity_not_found(tmp_store):
    graph = KnowledgeGraph(tmp_store)
    assert graph.get_entity("nonexistent") is None


def test_get_entity_context_facts(tmp_store):
    entity = Entity("Alice", "person")
    fact = Fact("Alice uses Python")
    tmp_store.add_entity(entity)
    tmp_store.add_fact(fact)
    tmp_store.add_about(fact.id, entity.id)
    graph = KnowledgeGraph(tmp_store)

    context = graph.get_entity_context(entity.id)

    assert len(context["facts"]) == 1
    assert context["facts"][0]["text"] == "Alice uses Python"


def test_get_entity_context_rules(tmp_store):
    entity = Entity("Alice", "person")
    rule = Rule("Always use tests", rule_type="fixed")
    tmp_store.add_entity(entity)
    tmp_store.add_rule(rule)
    tmp_store.add_has_rule(entity.id, rule.id)
    graph = KnowledgeGraph(tmp_store)

    context = graph.get_entity_context(entity.id)

    assert len(context["rules"]) == 1
    assert context["rules"][0]["text"] == "Always use tests"


def test_find_contradictions_empty(tmp_store):
    graph = KnowledgeGraph(tmp_store)
    assert graph.find_contradictions() == []


def test_find_contradictions(tmp_store):
    fact_a = Fact("Alice likes tea")
    fact_b = Fact("Alice dislikes tea")
    tmp_store.add_fact(fact_a)
    tmp_store.add_fact(fact_b)
    tmp_store.add_contradicts(fact_a.id, fact_b.id)
    graph = KnowledgeGraph(tmp_store)

    contradictions = graph.find_contradictions()

    assert len(contradictions) == 1
    assert contradictions[0]["fact_a"]["text"] == "Alice likes tea"


def test_get_recent_facts(tmp_store):
    tmp_store.add_fact(Fact("fact one"))
    tmp_store.add_fact(Fact("fact two"))
    tmp_store.add_fact(Fact("fact three"))
    graph = KnowledgeGraph(tmp_store)

    facts = graph.get_recent_facts(2)

    assert len(facts) == 2


def test_get_active_rules_all(tmp_store):
    tmp_store.add_rule(Rule("Always test", priority=60))
    tmp_store.add_rule(Rule("Never skip lint", rule_type="prohibition", priority=90))
    graph = KnowledgeGraph(tmp_store)

    rules = graph.get_active_rules()

    assert len(rules) == 2


def test_get_active_rules_by_entity(tmp_store):
    first = Entity("Alice", "person")
    second = Entity("Bob", "person")
    first_rule = Rule("Always test")
    second_rule = Rule("Never deploy Friday", rule_type="prohibition")
    tmp_store.add_entity(first)
    tmp_store.add_entity(second)
    tmp_store.add_rule(first_rule)
    tmp_store.add_rule(second_rule)
    tmp_store.add_has_rule(first.id, first_rule.id)
    tmp_store.add_has_rule(second.id, second_rule.id)
    graph = KnowledgeGraph(tmp_store)

    rules = graph.get_active_rules(entity_id=first.id)

    assert len(rules) == 1
    assert rules[0]["text"] == "Always test"


def test_export_to_memory_md(tmp_store):
    tmp_store.add_rule(Rule("Always test"))
    graph = KnowledgeGraph(tmp_store)

    output = graph.export_to_memory_md()

    assert "Rules" in output
