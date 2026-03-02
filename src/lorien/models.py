from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid

DEFAULT_AGENT_ID = "default"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Entity:
    name: str
    entity_type: str
    id: str = field(default_factory=_uid)
    kind: str = "entity"
    aliases: str = ""
    description: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    confidence: float = 1.0
    source: str = ""
    source_ref: str = ""
    status: str = "active"
    canonical_key: str = ""

    def __post_init__(self) -> None:
        if not self.canonical_key:
            import re

            normalized = re.sub(r"[^\w가-힣]", "", self.name.lower().replace(" ", "_"))
            self.canonical_key = f"{self.entity_type}:{normalized}"


@dataclass
class Decision:
    text: str
    id: str = field(default_factory=_uid)
    kind: str = "decision"
    decision_type: str = "action"   # "action" | "judgment" | "preference" | "plan"
    context: str = ""               # situation summary at decision time
    agent_id: str = DEFAULT_AGENT_ID
    confidence: float = 1.0
    status: str = "active"          # "active" | "revoked" | "superseded"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


@dataclass
class Agent:
    name: str
    id: str = field(default_factory=_uid)
    kind: str = "agent"
    agent_type: str = "llm"   # "llm" | "human" | "system"
    metadata: str = "{}"      # JSON blob (model version, config, etc.)
    created_at: str = field(default_factory=_now)
    last_active_at: str = field(default_factory=_now)
    status: str = "active"


@dataclass
class Fact:
    text: str
    id: str = field(default_factory=_uid)
    kind: str = "fact"
    fact_type: str = "statement"
    subject_id: str = ""
    predicate: str = ""
    object_id: str = ""
    valid_from: str = ""
    valid_to: str = ""
    negated: bool = False
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_confirmed: str = field(default_factory=_now)
    expires_at: str = ""   # empty = never expires
    version: int = 1
    agent_id: str = DEFAULT_AGENT_ID
    confidence: float = 1.0
    source: str = ""
    source_ref: str = ""
    status: str = "active"


@dataclass
class Rule:
    text: str
    id: str = field(default_factory=_uid)
    kind: str = "rule"
    rule_type: str = "preference"
    priority: int = 50
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    last_confirmed: str = field(default_factory=_now)
    expires_at: str = ""   # empty = never expires
    agent_id: str = DEFAULT_AGENT_ID
    confidence: float = 1.0
    source: str = ""
    source_ref: str = ""
    status: str = "active"
