"""Tests for LorienMemory — Mem0-compatible conversation memory interface."""
from __future__ import annotations

import pytest

from lorien.memory import LorienMemory
from lorien.schema import GraphStore


@pytest.fixture
def mem(tmp_path):
    """LorienMemory backed by a fresh temp DB (no LLM, no vectors for speed)."""
    db = str(tmp_path / "mem_test")
    return LorienMemory(db_path=db, enable_vectors=False)


MESSAGES = [
    {"role": "user", "content": "나는 커피보다 녹차를 더 좋아해"},
    {"role": "assistant", "content": "알겠어요, 녹차 선호를 기억할게요"},
    {"role": "user", "content": "그리고 절대 광고 이메일은 보내지 마"},
]


class TestLorienMemoryAdd:
    def test_add_returns_dict(self, mem):
        result = mem.add(MESSAGES, user_id="테스트유저")
        assert isinstance(result, dict)
        assert "facts" in result
        assert "rules" in result
        assert "entities" in result
        assert "edges" in result

    def test_add_empty_messages_returns_zeros(self, mem):
        result = mem.add([], user_id="테스트유저")
        assert result == {"entities": 0, "facts": 0, "rules": 0, "edges": 0}

    def test_add_system_messages_skipped(self, mem):
        msgs = [{"role": "system", "content": "You are helpful"}]
        result = mem.add(msgs, user_id="테스트유저")
        assert result == {"entities": 0, "facts": 0, "rules": 0, "edges": 0}

    def test_add_keyword_fallback_extracts_rules(self, mem):
        msgs = [{"role": "user", "content": "절대 광고 보내지 마"}]
        result = mem.add(msgs, user_id="규칙테스트")
        # keyword fallback: "절대" triggers rule extraction
        assert result["rules"] >= 1


class TestLorienMemoryGetAll:
    def test_get_all_empty(self, mem):
        result = mem.get_all(user_id="없는유저")
        assert result == []

    def test_get_all_after_add(self, mem):
        mem.add(MESSAGES, user_id="조회유저")
        all_mems = mem.get_all(user_id="조회유저")
        # keyword fallback produces facts + rules
        assert isinstance(all_mems, list)

    def test_get_all_global(self, mem):
        mem.add([{"role": "user", "content": "test fact"}], user_id="u1")
        result = mem.get_all()
        assert isinstance(result, list)

    def test_get_all_limit(self, mem):
        # Add many facts
        for i in range(15):
            mem.add([{"role": "user", "content": f"fact number {i}"}], user_id="limit테스트")
        result = mem.get_all(user_id="limit테스트", limit=5)
        assert len(result) <= 5


class TestLorienMemorySearch:
    def test_search_empty(self, mem):
        result = mem.search("없는검색어", user_id="없는유저")
        assert result == []

    def test_search_returns_list(self, mem):
        mem.add([{"role": "user", "content": "나는 Python을 좋아해"}], user_id="검색유저")
        result = mem.search("Python", user_id="검색유저")
        assert isinstance(result, list)

    def test_search_result_structure(self, mem):
        mem.add([{"role": "user", "content": "절대 rm -rf 실행 금지"}], user_id="구조테스트")
        results = mem.search("금지", user_id="구조테스트")
        for r in results:
            assert "id" in r
            assert "memory" in r
            assert "score" in r
            assert "type" in r
            assert r["type"] in ("fact", "rule")

    def test_search_global(self, mem):
        mem.add([{"role": "user", "content": "global keyword test"}], user_id="u1")
        result = mem.search("global")
        assert isinstance(result, list)


class TestLorienMemoryExclusiveFeatures:
    def test_get_entity_rules_empty(self, mem):
        rules = mem.get_entity_rules("없는엔티티")
        assert rules == []

    def test_get_contradictions_empty(self, mem):
        c = mem.get_contradictions()
        assert isinstance(c, list)
        assert len(c) == 0

    def test_delete_nonexistent(self, mem):
        # Should not raise
        result = mem.delete("nonexistent-id-12345")
        assert result is True
