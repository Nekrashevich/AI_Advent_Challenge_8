import json

import numpy as np

from budget_agent import data, ollama
from budget_agent.config import EMBED_MODEL, INDEX_JSON


def _normalize(matrix):
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-10)


class BudgetIndex:
    def __init__(self, docs, matrix, model=EMBED_MODEL):
        self.docs = docs
        self.matrix = _normalize(np.array(matrix, dtype=np.float32))
        self.model = model

    @classmethod
    def build(cls):
        docs = data.docs_for_retrieval()
        vectors = ollama.embed_texts([doc["text"] for doc in docs])
        return cls(docs, vectors)

    @classmethod
    def load(cls):
        payload = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        return cls(payload["docs"], payload["vectors"], payload["model"])

    def save(self):
        INDEX_JSON.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "docs": self.docs,
            "vectors": self.matrix.round(6).tolist(),
        }
        INDEX_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return INDEX_JSON

    def search(self, query, top_k=6):
        vector = np.array(ollama.embed_texts([query])[0], dtype=np.float32)
        vector = _normalize(vector.reshape(1, -1))[0]
        scores = self.matrix @ vector
        order = np.argsort(scores)[::-1][:top_k]
        return [(float(scores[i]), self.docs[i]) for i in order]


def ensure_index(rebuild=False):
    if INDEX_JSON.exists() and not rebuild:
        return BudgetIndex.load()
    index = BudgetIndex.build()
    index.save()
    return index


def context_block(hits):
    return "\n\n".join(
        f"=== {doc['id']} | score {score:.3f} | {doc['title']}\n{doc['text']}"
        for score, doc in hits
    )
