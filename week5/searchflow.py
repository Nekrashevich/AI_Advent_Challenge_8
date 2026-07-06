import json

import vectors
from model import chat, CHEAP_MODEL

DEFAULTS = {
    "rewrite": False,
    "rerank": False,
    "threshold": 0.42,
    "top_n": 20,
    "top_k": 5,
    "rerank_min": 4,
}

REWRITE_SYSTEM = (
    "Ты переписываешь вопрос пользователя в самодостаточный поисковый запрос для векторного "
    "поиска по базе знаний проекта. Раскрой местоимения и сокращения, добавь ключевые термины, "
    "убери вежливые обороты. Ответ — только текст запроса, одна строка."
)

RERANK_SYSTEM = (
    "Ты оцениваешь релевантность фрагментов базы знаний вопросу. Для каждого фрагмента поставь "
    "целую оценку 0-10: 10 — прямо отвечает на вопрос, 0 — не имеет отношения. "
    'Верни строго JSON вида {"scores": {"1": 7, "2": 0}} по номерам фрагментов.'
)


def rewrite_query(question, history_text=""):
    prompt = question
    if history_text:
        prompt = f"Контекст диалога:\n{history_text}\n\nВопрос: {question}"
    return chat(
        [{"role": "system", "content": REWRITE_SYSTEM}, {"role": "user", "content": prompt}],
        model=CHEAP_MODEL,
        temperature=0,
    )


def rerank_scores(question, hits):
    numbered = "\n\n".join(
        f"[{position}] ({chunk['title']} — {chunk['section']})\n{chunk['text'][:800]}"
        for position, (_, chunk) in enumerate(hits, 1)
    )
    raw = chat(
        [
            {"role": "system", "content": RERANK_SYSTEM},
            {"role": "user", "content": f"Вопрос: {question}\n\nФрагменты:\n{numbered}"},
        ],
        model=CHEAP_MODEL,
        temperature=0,
        json_mode=True,
    )
    scores = json.loads(raw).get("scores", {})
    return {int(k): float(v) for k, v in scores.items()}


def retrieve(index, question, settings=None, history_text=""):
    settings = {**DEFAULTS, **(settings or {})}
    query = question
    if settings["rewrite"]:
        query = rewrite_query(question, history_text)
    raw_hits = index.search(vectors.embed_one(query), settings["top_n"])
    passed = [(score, chunk) for score, chunk in raw_hits if score >= settings["threshold"]]
    dropped_threshold = [(score, chunk) for score, chunk in raw_hits if score < settings["threshold"]]
    reranked = passed
    dropped_rerank = []
    llm_scores = {}
    if settings["rerank"] and passed:
        llm_scores = rerank_scores(question, passed)
        scored = [
            (llm_scores.get(position, 0), score, chunk)
            for position, (score, chunk) in enumerate(passed, 1)
        ]
        scored.sort(key=lambda item: item[0], reverse=True)
        reranked = [(score, chunk) for llm, score, chunk in scored if llm >= settings["rerank_min"]]
        dropped_rerank = [(score, chunk) for llm, score, chunk in scored if llm < settings["rerank_min"]]
    final = reranked[: settings["top_k"]]
    return {
        "question": question,
        "query": query,
        "settings": settings,
        "raw": raw_hits,
        "dropped_threshold": dropped_threshold,
        "dropped_rerank": dropped_rerank,
        "llm_scores": llm_scores,
        "final": final,
        "best_score": raw_hits[0][0] if raw_hits else 0.0,
    }
