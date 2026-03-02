from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Entity, Fact, Rule
from .schema import GraphStore


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

HEADER_RE = re.compile(r"^#{1,6}\s+")


class LorienIngester:
    def __init__(
        self,
        store: GraphStore,
        llm_model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.store = store
        self.llm_model = llm_model
        self.api_key = api_key
        self.base_url = base_url or "https://api.openai.com/v1"
        self._entity_cache: dict[str, str] = {}

    def ingest_text(self, text: str, source: str = "manual") -> IngestResult:
        text = text.strip()
        if not text:
            return IngestResult(errors=["Empty text"])
        triples = self._llm_extract(text) if (self.llm_model and self.api_key) else None
        if triples is None:
            triples = self._keyword_extract(text)
        return self._store_triples(triples, source)

    def ingest_memory_md(self, path: str, verbose: bool = False) -> IngestResult:
        content = Path(path).read_text(encoding="utf-8")
        result = IngestResult()
        lines = content.split("\n")
        sections: list[tuple[str, list[str]]] = []
        current_header = "general"
        current_lines: list[str] = []
        for line in lines:
            if HEADER_RE.match(line):
                if current_lines:
                    sections.append((current_header, current_lines))
                current_header = HEADER_RE.sub("", line).strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines:
            sections.append((current_header, current_lines))

        total = len([s for s in sections if "\n".join(s[1]).strip()])
        done = 0
        for header, sec_lines in sections:
            body = "\n".join(sec_lines).strip()
            if not body:
                continue
            done += 1
            if verbose and self.llm_model:
                print(f"  [{done}/{total}] {header[:50]}", flush=True)
            section_source = f"MEMORY.md:{header}"
            current = self.ingest_text(body, source=section_source)
            result.entities_added += current.entities_added
            result.facts_added += current.facts_added
            result.rules_added += current.rules_added
            result.edges_added += current.edges_added
            result.errors.extend(current.errors)
        return result

    def _llm_extract(self, text: str) -> ExtractedTriples | None:
        try:
            if self.llm_model and self.llm_model.startswith("claude"):
                return self._anthropic_extract(text)
            return self._openai_extract(text)
        except Exception:
            return None

    def _anthropic_extract(self, text: str) -> ExtractedTriples | None:
        """Anthropic Messages API (claude-* models)."""
        import urllib.request

        combined = SYSTEM_PROMPT + "\n\n" + USER_PROMPT.format(text=text)
        payload = json.dumps(
            {
                "model": self.llm_model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": combined}],
            }
        ).encode()
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = json.loads(response.read())
        content = raw["content"][0]["text"]
        # Strip markdown code fences if present
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            return self._parse_llm_output(json.loads(json_match.group()))
        return None

    def _openai_extract(self, text: str) -> ExtractedTriples | None:
        """OpenAI-compatible API."""
        import urllib.request

        payload = json.dumps(
            {
                "model": self.llm_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": USER_PROMPT.format(text=text)},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = json.loads(response.read())
        content = raw["choices"][0]["message"]["content"]
        return self._parse_llm_output(json.loads(content))

    def _parse_llm_output(self, raw: dict[str, Any]) -> ExtractedTriples:
        triples = ExtractedTriples()
        for entity in raw.get("entities", []):
            triples.entities.append(
                ExtractedEntity(
                    name=entity.get("name", ""),
                    entity_type=entity.get("entity_type", "concept"),
                    aliases=entity.get("aliases", []),
                    description=entity.get("description", ""),
                    confidence=float(entity.get("confidence", 0.8)),
                )
            )
        for fact in raw.get("facts", []):
            triples.facts.append(
                ExtractedFact(
                    text=fact.get("text", ""),
                    subject=fact.get("subject", "user"),
                    predicate=fact.get("predicate", "noted"),
                    object=fact.get("object"),
                    fact_type=fact.get("fact_type", "observation"),
                    confidence=float(fact.get("confidence", 0.8)),
                    negated=bool(fact.get("negated", False)),
                )
            )
        for rule in raw.get("rules", []):
            triples.rules.append(
                ExtractedRule(
                    text=rule.get("text", ""),
                    subject=rule.get("subject", "user"),
                    rule_type=rule.get("rule_type", "preference"),
                    priority=int(rule.get("priority", 50)),
                    confidence=float(rule.get("confidence", 0.9)),
                )
            )
        for relation in raw.get("relations", []):
            triples.relations.append(
                ExtractedRelation(
                    source=relation.get("source", ""),
                    target=relation.get("target", ""),
                    rel_type=relation.get("rel_type", "RELATED_TO"),
                    confidence=float(relation.get("confidence", 0.7)),
                )
            )
        return triples

    def _keyword_extract(self, text: str) -> ExtractedTriples:
        triples = ExtractedTriples()
        user_added = False
        for line in text.split("\n"):
            stripped = line.strip().lstrip("-•* ")
            if not stripped or HEADER_RE.match(stripped):
                continue
            matched = None
            lowered = stripped.lower()
            for marker, (rule_type, priority) in RULE_MARKERS.items():
                if marker.lower() in lowered or marker in stripped:
                    matched = (rule_type, priority)
                    break
            if matched:
                rule_type, priority = matched
                triples.rules.append(
                    ExtractedRule(
                        text=stripped,
                        subject="user",
                        rule_type=rule_type,
                        priority=priority,
                        confidence=0.95,
                    )
                )
                if not user_added:
                    triples.entities.append(
                        ExtractedEntity(name="user", entity_type="person", confidence=1.0)
                    )
                    user_added = True
            elif len(stripped) > 10:
                triples.facts.append(
                    ExtractedFact(text=stripped, subject="user", confidence=0.5)
                )
                if not user_added:
                    triples.entities.append(
                        ExtractedEntity(name="user", entity_type="person", confidence=1.0)
                    )
                    user_added = True
        return triples

    @staticmethod
    def _canonical_key(entity_type: str, name: str) -> str:
        normalized = re.sub(r"[^\w가-힣]", "", name.lower().replace(" ", "_"))
        return f"{entity_type}:{normalized}"

    def _resolve_entity(self, name: str, entity_type: str, aliases: list[str]) -> tuple[str, bool]:
        """Resolve an entity by name/aliases, creating if needed.

        Returns (entity_id, is_new) where is_new is True only if a new
        Entity node was created.
        """
        canonical = self._canonical_key(entity_type, name)
        if canonical in self._entity_cache:
            return self._entity_cache[canonical], False

        existing = self.store.find_entity_by_canonical_key(canonical)
        if existing:
            self._entity_cache[canonical] = existing["id"]
            return existing["id"], False

        for alias in [name] + aliases:
            found = self.store.find_entity_by_alias(alias, entity_type=entity_type)
            if found:
                self._entity_cache[canonical] = found["id"]
                return found["id"], False

        entity = Entity(
            name=name,
            entity_type=entity_type,
            aliases=",".join(aliases),
            confidence=0.8,
            source="ingest",
        )
        self.store.add_entity(entity)
        self._entity_cache[canonical] = entity.id
        return entity.id, True

    def _store_triples(self, triples: ExtractedTriples, source: str) -> IngestResult:
        result = IngestResult()
        name_to_id: dict[str, str] = {}

        for ent in triples.entities:
            if not ent.name:
                continue
            try:
                entity_id, is_new = self._resolve_entity(ent.name, ent.entity_type, ent.aliases)
                name_to_id[ent.name.lower()] = entity_id
                if is_new:
                    result.entities_added += 1
            except Exception as exc:
                result.errors.append(f"entity error: {exc}")

        for fact in triples.facts:
            if not fact.text:
                continue
            try:
                stored = Fact(
                    text=fact.text,
                    fact_type=fact.fact_type,
                    subject_id=name_to_id.get(fact.subject.lower(), ""),
                    predicate=fact.predicate,
                    object_id=name_to_id.get((fact.object or "").lower(), ""),
                    negated=fact.negated,
                    confidence=fact.confidence,
                    source=source,
                )
                self.store.add_fact(stored)
                result.facts_added += 1
                if stored.subject_id:
                    self.store.add_about(stored.id, stored.subject_id)
                    result.edges_added += 1
            except Exception as exc:
                result.errors.append(f"fact error: {exc}")

        for rule in triples.rules:
            if not rule.text:
                continue
            try:
                entity_id = name_to_id.get(rule.subject.lower(), "")
                stored = Rule(
                    text=rule.text,
                    rule_type=rule.rule_type,
                    priority=rule.priority,
                    confidence=rule.confidence,
                    source=source,
                )
                self.store.add_rule(stored)
                result.rules_added += 1
                if entity_id:
                    self.store.add_has_rule(entity_id, stored.id)
                    result.edges_added += 1
            except Exception as exc:
                result.errors.append(f"rule error: {exc}")

        for relation in triples.relations:
            try:
                source_id = name_to_id.get(relation.source.lower())
                target_id = name_to_id.get(relation.target.lower())
                if not source_id or not target_id:
                    continue
                # CAUSED/CONTRADICTS are Fact→Fact edges but LLM returns Entity names.
                # v0.1: encode semantic type in RELATED_TO.relation property.
                relation_label = relation.rel_type.lower()  # "caused", "contradicts", "related_to"
                self.store.add_related_to(source_id, target_id, relation_label)
                result.edges_added += 1
            except Exception as exc:
                result.errors.append(f"relation error: {exc}")

        return result
