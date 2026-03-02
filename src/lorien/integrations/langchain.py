"""LangChain adapter for lorien.

Provides a drop-in BaseMemory implementation that stores conversation
history in lorien's knowledge graph with full ontology + contradiction detection.

Usage:
    from langchain.chains import ConversationChain
    from lorien.integrations.langchain import LorienChatMemory

    memory = LorienChatMemory(user_id="alice", enable_vectors=True)
    chain = ConversationChain(llm=llm, memory=memory)
"""
from __future__ import annotations

from typing import Any

from ..memory import LorienMemory


class LorienChatMemory:
    """LangChain-compatible BaseMemory backed by lorien knowledge graph.

    Stores conversation messages as Facts with full ontology support.
    Compatible with LangChain's ConversationChain and similar chains.

    Args:
        user_id: User identifier for memory isolation
        db_path: Path to lorien DB (default: ~/.lorien/db)
        model: LLM model for extraction (default: keyword fallback)
        enable_vectors: Enable semantic search (requires sentence-transformers)
        memory_key: LangChain memory key name (default: "history")
        human_prefix: Label for human turns
        ai_prefix: Label for AI turns
    """

    memory_key: str = "history"
    human_prefix: str = "Human"
    ai_prefix: str = "AI"

    def __init__(
        self,
        user_id: str,
        db_path: str | None = None,
        model: str | None = None,
        enable_vectors: bool = False,
        memory_key: str = "history",
        human_prefix: str = "Human",
        ai_prefix: str = "AI",
    ) -> None:
        self.user_id = user_id
        self.memory_key = memory_key
        self.human_prefix = human_prefix
        self.ai_prefix = ai_prefix
        self._lorien = LorienMemory(
            db_path=db_path,
            model=model,
            enable_vectors=enable_vectors,
        )
        self._buffer: list[dict[str, str]] = []

    # ── LangChain BaseMemory interface ──────────────────────────────

    @property
    def memory_variables(self) -> list[str]:
        """LangChain: variables injected into the prompt."""
        return [self.memory_key]

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """LangChain: load memory into prompt context.

        Returns recent conversation history + relevant semantic memories.
        """
        query = " ".join(str(v) for v in inputs.values())

        # Semantic search for relevant past facts
        if self._lorien.vectors:
            results = self._lorien.search(query, user_id=self.user_id, limit=5)
            context_lines = [f"[Past fact] {r['memory']}" for r in results]
        else:
            context_lines = []

        # Recent conversation buffer
        buffer_text = "\n".join(
            f"{self.human_prefix if m['role'] == 'user' else self.ai_prefix}: {m['content']}"
            for m in self._buffer[-10:]  # Last 5 turns
        )

        context = "\n".join(context_lines)
        full_history = f"{context}\n{buffer_text}".strip() if context else buffer_text

        return {self.memory_key: full_history}

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, str]) -> None:
        """LangChain: save a conversation turn to lorien."""
        human_msg = next(iter(inputs.values()), "")
        ai_msg = next(iter(outputs.values()), "")

        messages = [
            {"role": "user",      "content": str(human_msg)},
            {"role": "assistant", "content": str(ai_msg)},
        ]
        self._buffer.extend(messages)

        # Store in lorien graph
        self._lorien.add(messages, user_id=self.user_id)

    def clear(self) -> None:
        """LangChain: clear buffer (does NOT delete from lorien graph)."""
        self._buffer.clear()

    # ── Extra lorien-specific methods ───────────────────────────────

    def get_contradictions(self) -> list[dict]:
        """Return auto-detected contradictions in the knowledge graph."""
        return self._lorien.get_contradictions()

    def get_rules(self) -> list[dict]:
        """Return all rules for this user."""
        return self._lorien.get_entity_rules(self.user_id)

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """Semantic search over user's memories."""
        return self._lorien.search(query, user_id=self.user_id, limit=limit)

    @property
    def store(self):
        """Direct access to the underlying GraphStore."""
        return self._lorien.store
