import json
import time
from pathlib import Path

import numpy as np

import vectors

STORE = Path(__file__).resolve().parent / "runtime_store"


class VectorIndex:
    def __init__(self, strategy, chunks, matrix, built_at=None):
        self.strategy = strategy
        self.chunks = chunks
        self.matrix = matrix
        self.built_at = built_at or time.strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def build(cls, strategy, chunks, progress=None):
        matrix = vectors.embed_texts([c["text"] for c in chunks], progress=progress)
        return cls(strategy, chunks, matrix)

    def save(self):
        STORE.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": vectors.EMBED_MODEL,
            "strategy": self.strategy,
            "built_at": self.built_at,
            "dim": int(self.matrix.shape[1]),
            "chunks": [
                {**chunk, "vector": vector}
                for chunk, vector in zip(self.chunks, self.matrix.round(6).tolist())
            ],
        }
        path = STORE / f"index-{self.strategy}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    @classmethod
    def load(cls, strategy):
        path = STORE / f"index-{strategy}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        chunks = []
        vectors = []
        for entry in payload["chunks"]:
            vectors.append(entry.pop("vector"))
            chunks.append(entry)
        matrix = np.array(vectors, dtype=np.float32)
        return cls(payload["strategy"], chunks, matrix, payload["built_at"])

    @classmethod
    def exists(cls, strategy):
        return (STORE / f"index-{strategy}.json").is_file()

    def search(self, query_vector, top_k=5):
        scores = self.matrix @ query_vector
        order = np.argsort(scores)[::-1][:top_k]
        return [(float(scores[i]), self.chunks[i]) for i in order]

    def search_text(self, query, top_k=5):
        return self.search(vectors.embed_one(query), top_k)
