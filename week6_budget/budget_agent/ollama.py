import time

import requests

from budget_agent.config import EMBED_MODEL, LOCAL_MODEL, OLLAMA_URL


def is_available():
    try:
        requests.get(f"{OLLAMA_URL}/api/version", timeout=3).raise_for_status()
        return True
    except requests.RequestException:
        return False


def list_models():
    response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
    response.raise_for_status()
    return [entry["name"] for entry in response.json().get("models", [])]


def stats(payload, seconds):
    eval_count = payload.get("eval_count", 0)
    eval_ns = payload.get("eval_duration", 0) or 1
    return {
        "seconds": round(seconds, 2),
        "tokens": eval_count,
        "tok_per_s": round(eval_count / (eval_ns / 1e9), 1),
        "model": payload.get("model", ""),
        "prompt_tokens": payload.get("prompt_eval_count", 0),
    }


def chat(messages, model=LOCAL_MODEL, temperature=0.3, num_ctx=4096, num_predict=360, timeout=300):
    started = time.time()
    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["message"]["content"].strip(), stats(payload, time.time() - started)


def ask(prompt, system="", **kwargs):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat(messages, **kwargs)


def embed_texts(texts, model=EMBED_MODEL):
    response = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": model, "input": texts},
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["embeddings"]
