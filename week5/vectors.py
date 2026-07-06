import numpy as np
import requests

OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "bge-m3"
BATCH = 16


def is_available():
    try:
        requests.get(f"{OLLAMA_URL}/api/version", timeout=3)
        return True
    except requests.RequestException:
        return False


def embed_texts(texts, progress=None):
    vectors = []
    for start in range(0, len(texts), BATCH):
        batch = texts[start: start + BATCH]
        response = requests.post(
            f"{OLLAMA_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": batch},
            timeout=300,
        )
        response.raise_for_status()
        vectors.extend(response.json()["embeddings"])
        if progress:
            progress(min(start + BATCH, len(texts)), len(texts))
    matrix = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.maximum(norms, 1e-10)


def embed_one(text):
    return embed_texts([text])[0]
