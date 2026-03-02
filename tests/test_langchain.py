"""Tests for LangChain integration adapter."""
from __future__ import annotations

import pytest

from lorien.integrations.langchain import LorienChatMemory


@pytest.fixture
def memory(tmp_path):
    return LorienChatMemory(
        user_id="test_user",
        db_path=str(tmp_path / "lc_test"),
        enable_vectors=False,
    )


class TestLorienChatMemory:
    def test_memory_variables(self, memory):
        assert memory.memory_variables == ["history"]

    def test_save_and_load(self, memory):
        memory.save_context(
            {"input": "What's the capital of France?"},
            {"response": "Paris is the capital of France."},
        )
        loaded = memory.load_memory_variables({"input": "France"})
        assert "history" in loaded
        assert "Paris" in loaded["history"]

    def test_multiple_turns(self, memory):
        memory.save_context({"input": "Hello"}, {"response": "Hi there!"})
        memory.save_context({"input": "I'm Alice"}, {"response": "Nice to meet you, Alice!"})
        loaded = memory.load_memory_variables({"input": "Alice"})
        assert "Alice" in loaded["history"]

    def test_clear_buffer(self, memory):
        memory.save_context({"input": "Test"}, {"response": "OK"})
        memory.clear()
        loaded = memory.load_memory_variables({"input": "test"})
        assert loaded["history"] == ""

    def test_custom_memory_key(self, tmp_path):
        mem = LorienChatMemory(
            user_id="u1",
            db_path=str(tmp_path / "custom_key"),
            memory_key="chat_history",
            enable_vectors=False,
        )
        assert mem.memory_variables == ["chat_history"]

    def test_get_contradictions_returns_list(self, memory):
        result = memory.get_contradictions()
        assert isinstance(result, list)

    def test_get_rules_returns_list(self, memory):
        result = memory.get_rules()
        assert isinstance(result, list)

    def test_search_returns_list(self, memory):
        memory.save_context(
            {"input": "I love hiking"},
            {"response": "Great outdoor activity!"},
        )
        results = memory.search("outdoor activities")
        assert isinstance(results, list)

    def test_store_is_accessible(self, memory):
        from lorien.schema import GraphStore
        assert isinstance(memory.store, GraphStore)
