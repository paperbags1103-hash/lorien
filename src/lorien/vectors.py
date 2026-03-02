"""VectorIndex — SQLite sidecar vector store for lorien.

Stores sentence embeddings alongside Kuzu graph DB.
Uses paraphrase-multilingual-MiniLM-L12-v2 (Korean+English, local, free).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

# Default model — multilingual, 384-dim, ~110MB, runs on CPU
DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
SIMILARITY_THRESHOLD = 0.30  # min cosine similarity to return


class VectorIndex:
    """SQLite-backed vector index with cosine similarity search.

    Stored alongside Kuzu DB (same parent directory).
    """

    def __init__(self, db_path: str, model_name: str = DEFAULT_MODEL) -> None:
        kuzu_path = Path(db_path).expanduser()
        # Place vectors.db next to the Kuzu database file
        vec_path = kuzu_path.parent / "vectors.db"
        vec_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(vec_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS embeddings (
                node_id   TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                text      TEXT NOT NULL,
                vector    BLOB NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_type ON embeddings(node_type)"
        )
        self._conn.commit()

        self._model_name = model_name
        self._model = None  # lazy-loaded on first use

    # ─── Internal ────────────────────────────────────────────────────────────

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def _encode(self, text: str) -> np.ndarray:
        model = self._get_model()
        return model.encode(text, normalize_embeddings=True).astype(np.float32)

    # ─── Write ───────────────────────────────────────────────────────────────

    def add(self, node_id: str, node_type: str, text: str) -> None:
        """Encode text and store embedding."""
        if not text or not text.strip():
            return
        vec = self._encode(text)
        self._conn.execute(
            "INSERT OR REPLACE INTO embeddings VALUES (?,?,?,?)",
            (node_id, node_type, text, vec.tobytes()),
        )
        self._conn.commit()

    def remove(self, node_id: str) -> None:
        """Delete embedding by node_id."""
        self._conn.execute("DELETE FROM embeddings WHERE node_id=?", (node_id,))
        self._conn.commit()

    # ─── Search ──────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 10,
        node_type: Optional[str] = None,
        threshold: float = SIMILARITY_THRESHOLD,
        exclude_ids: Optional[set[str]] = None,
    ) -> list[dict]:
        """Return top_k most similar nodes to query.

        Args:
            query: Search text
            top_k: Max results
            node_type: Filter to 'Fact' or 'Rule' (None = all)
            threshold: Minimum cosine similarity (0-1)
            exclude_ids: Node IDs to skip

        Returns:
            List of {"id", "text", "node_type", "score"} dicts
        """
        if not query or not query.strip():
            return []

        q_vec = self._encode(query)

        if node_type:
            rows = self._conn.execute(
                "SELECT node_id, node_type, text, vector FROM embeddings WHERE node_type=?",
                (node_type,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT node_id, node_type, text, vector FROM embeddings"
            ).fetchall()

        if not rows:
            return []

        ids = [r[0] for r in rows]
        types = [r[1] for r in rows]
        texts = [r[2] for r in rows]
        vecs = np.stack([np.frombuffer(r[3], dtype=np.float32) for r in rows])

        # Cosine similarity (vectors are L2-normalized)
        scores = vecs @ q_vec

        # Sort descending
        order = np.argsort(scores)[::-1]
        results = []
        for i in order:
            if len(results) >= top_k:
                break
            nid = ids[i]
            if exclude_ids and nid in exclude_ids:
                continue
            score = float(scores[i])
            if score < threshold:
                break
            results.append({
                "id": nid,
                "node_type": types[i],
                "text": texts[i],
                "score": score,
            })
        return results

    def similar_to(
        self,
        node_id: str,
        top_k: int = 5,
        node_type: Optional[str] = None,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> list[dict]:
        """Find nodes similar to an existing node (by id)."""
        row = self._conn.execute(
            "SELECT text FROM embeddings WHERE node_id=?", (node_id,)
        ).fetchone()
        if not row:
            return []
        return self.search(
            row[0],
            top_k=top_k + 1,
            node_type=node_type,
            threshold=threshold,
            exclude_ids={node_id},
        )

    # ─── Stats ───────────────────────────────────────────────────────────────

    def count(self, node_type: Optional[str] = None) -> int:
        if node_type:
            return self._conn.execute(
                "SELECT count(*) FROM embeddings WHERE node_type=?", (node_type,)
            ).fetchone()[0]
        return self._conn.execute("SELECT count(*) FROM embeddings").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
