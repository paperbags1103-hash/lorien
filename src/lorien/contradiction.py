"""ContradictionDetector — automatic contradiction detection using vector similarity + LLM."""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Optional

from .schema import GraphStore

CONTRADICTION_PROMPT = """Do these two statements DIRECTLY CONTRADICT each other?
Answer ONLY 'yes' or 'no'.

Statement A: {a}
Statement B: {b}"""


class ContradictionDetector:
    """Detects contradictions between new facts/rules and existing ones.

    Uses vector similarity to find candidates, then LLM to confirm.
    Falls back to heuristic-only (negation patterns) if no LLM configured.
    """

    # Negation pairs — offline heuristic
    NEGATION_PAIRS = [
        ("좋아", "싫어"),
        ("좋아해", "싫어해"),
        ("좋다", "싫다"),
        ("허용", "금지"),
        ("허용한다", "금지한다"),
        ("가능", "불가능"),
        ("해야", "하지 말"),
        ("반드시", "절대"),
        ("always", "never"),
        ("must", "must not"),
        ("allow", "prohibit"),
        ("enable", "disable"),
        ("할 수 있다", "할 수 없다"),
    ]

    def __init__(
        self,
        store: GraphStore,
        vector_index=None,  # VectorIndex | None
        llm_model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        use_openclaw: bool = False,
        similarity_threshold: float = 0.55,
    ) -> None:
        self.store = store
        self.vectors = vector_index
        self.llm_model = llm_model
        self.api_key = api_key
        self.base_url = base_url or "https://api.openai.com/v1"
        self._use_openclaw = use_openclaw
        self.threshold = similarity_threshold

    def check_and_record(self, new_node_id: str, new_text: str, node_type: str = "Fact") -> int:
        """Check if new_text contradicts existing facts/rules. Returns number of contradictions found.

        Creates CONTRADICTS edges for confirmed contradictions.
        """
        if not new_text or not new_text.strip():
            return 0

        # Find candidates via vector similarity
        candidates = []
        if self.vectors:
            similar = self.vectors.search(
                new_text,
                top_k=8,
                node_type=node_type,
                threshold=self.threshold,
                exclude_ids={new_node_id},
            )
            candidates = similar
        else:
            # No vector index: heuristic only on recent facts
            rows = self.store.query(
                f"MATCH (n:{node_type}) WHERE n.status = 'active' AND n.id <> '{new_node_id}' "
                f"RETURN n.id, n.text LIMIT 50"
            )
            for nid, text in rows:
                if self._heuristic_contradiction(new_text, text):
                    candidates.append({"id": nid, "text": text, "score": 0.8})

        found = 0
        for candidate in candidates:
            cid = candidate["id"]
            ctext = candidate["text"]
            if self._is_contradiction(new_text, ctext):
                try:
                    if node_type == "Fact":
                        self.store.add_contradicts(new_node_id, cid)
                    # For Rules: store as Fact contradiction if both are Facts
                    found += 1
                except Exception:
                    pass

        return found

    def _is_contradiction(self, text_a: str, text_b: str) -> bool:
        """Check if two texts contradict — LLM if available, heuristic fallback."""
        # Heuristic first (fast, offline)
        if self._heuristic_contradiction(text_a, text_b):
            return True
        # LLM confirmation
        if self.llm_model and self.api_key:
            return self._llm_contradiction_check(text_a, text_b)
        return False

    def _heuristic_contradiction(self, a: str, b: str) -> bool:
        """Simple negation-pair heuristic."""
        a_lower = a.lower()
        b_lower = b.lower()
        for pos, neg in self.NEGATION_PAIRS:
            if pos in a_lower and neg in b_lower:
                return True
            if neg in a_lower and pos in b_lower:
                return True
        return False

    def _llm_contradiction_check(self, text_a: str, text_b: str) -> bool:
        """Ask LLM if two statements contradict each other."""
        try:
            prompt = CONTRADICTION_PROMPT.format(a=text_a, b=text_b)
            if self._use_openclaw or not self.llm_model.startswith("claude"):
                payload = json.dumps({
                    "model": self.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 5,
                    "temperature": 0.0,
                }).encode()
                req = urllib.request.Request(
                    f"{self.base_url}/chat/completions",
                    data=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
            else:
                payload = json.dumps({
                    "model": self.llm_model,
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": prompt}],
                }).encode()
                req = urllib.request.Request(
                    "https://api.anthropic.com/v1/messages",
                    data=payload,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = json.loads(resp.read())
            if "choices" in raw:
                answer = raw["choices"][0]["message"]["content"]
            else:
                answer = raw["content"][0]["text"]
            return answer.strip().lower().startswith("yes")
        except Exception:
            return False

    @classmethod
    def from_ingester(cls, ingester) -> "ContradictionDetector":
        """Create a ContradictionDetector from an existing LorienIngester."""
        return cls(
            store=ingester.store,
            vector_index=ingester.vectors,
            llm_model=ingester.llm_model,
            api_key=ingester.api_key,
            base_url=ingester.base_url,
            use_openclaw=ingester._use_openclaw,
        )
