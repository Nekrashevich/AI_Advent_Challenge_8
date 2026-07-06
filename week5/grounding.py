import json
import re

from model import chat, MAIN_MODEL
from searchflow import retrieve

NO_RAG_SYSTEM = (
    "Ты ассистент разработчика. Отвечай на вопрос кратко, на русском. "
    "Если не знаешь точного ответа про конкретный проект — отвечай из общих знаний."
)

RAG_SYSTEM = (
    "Ты ассистент по базе знаний MDN Web Docs по JavaScript. Отвечай ТОЛЬКО на основе "
    "приложенных фрагментов базы. Ничего не выдумывай сверх них. Каждый факт бери из фрагментов. "
    "Верни строго JSON:\n"
    '{"answer": "ответ на русском, 2-6 предложений", '
    '"sources": [{"chunk_id": "...", "reason": "что взято из этого фрагмента"}], '
    '"quotes": [{"chunk_id": "...", "text": "дословная цитата из фрагмента, 1-2 предложения"}]}\n'
    "В sources и quotes указывай только реально использованные chunk_id из приложенных. "
    "Цитаты копируй ДОСЛОВНО, символ в символ."
)

REFUSAL = (
    "В базе знаний нет достаточно релевантного ответа на этот вопрос. "
    "Уточни формулировку или спроси о том, что описано в документах проекта."
)


def _context_block(final_hits):
    return "\n\n".join(
        f"=== chunk_id: {chunk['chunk_id']}\n"
        f"документ: {chunk['title']} | секция: {chunk['section']} | файл: {chunk['source']}\n"
        f"{chunk['text']}"
        for _, chunk in final_hits
    )


def answer_no_rag(question):
    return chat(
        [{"role": "system", "content": NO_RAG_SYSTEM}, {"role": "user", "content": question}],
        model=MAIN_MODEL,
    )


def _normalized_contains(needle, haystack):
    return bool(needle) and " ".join(needle.split()) in " ".join(haystack.split())


def _quote_terms(*texts):
    joined = " ".join(texts).lower()
    return {w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", joined)
            if w not in {"the", "and", "for", "with", "this", "that", "you", "are"}}


def _exact_quote_from_chunk(chunk_text, question="", draft=""):
    terms = _quote_terms(question, draft)
    candidates = []
    for match in re.finditer(r"[^.!?\n]+[.!?]", chunk_text):
        text = match.group(0).strip()
        if not 40 <= len(text) <= 260:
            continue
        if text.startswith(("---", "{{", "```")) or "```" in text or "![" in text:
            continue
        lowered = text.lower()
        score = sum(1 for term in terms if term in lowered)
        score += 2 if 80 <= len(text) <= 220 else 0
        candidates.append((score, match.start(), text))
    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][2]
    return chunk_text.strip()[:220]


def _validate_quotes(quotes, chunks_by_id, question=""):
    validated = []
    for quote in quotes:
        chunk = chunks_by_id.get(quote.get("chunk_id"))
        text = (quote.get("text") or "").strip()
        ok = bool(chunk) and _normalized_contains(text, chunk["text"])
        if not ok and chunk:
            text = _exact_quote_from_chunk(chunk["text"], question, text)
            ok = _normalized_contains(text, chunk["text"])
            validated.append({**quote, "text": text, "verified": ok, "repaired": ok})
        else:
            validated.append({**quote, "verified": ok})
    return validated


def generate_answer(question, result, history_messages=None):
    if not result["final"]:
        return {"status": "no_context", "answer": REFUSAL, "sources": [], "quotes": [],
                "retrieval": result}
    context = _context_block(result["final"])
    messages = [{"role": "system", "content": RAG_SYSTEM}]
    if history_messages:
        messages.extend(history_messages)
    messages.append({"role": "user", "content": f"Фрагменты базы:\n{context}\n\nВопрос: {question}"})
    raw = chat(messages, model=MAIN_MODEL, json_mode=True)
    payload = json.loads(raw)
    chunks_by_id = {chunk["chunk_id"]: chunk for _, chunk in result["final"]}
    sources = []
    for source in payload.get("sources", []):
        chunk = chunks_by_id.get(source.get("chunk_id"))
        if chunk:
            sources.append({
                "chunk_id": chunk["chunk_id"],
                "source": chunk["source"],
                "title": chunk["title"],
                "section": chunk["section"],
                "reason": source.get("reason", ""),
            })
    quotes = _validate_quotes(payload.get("quotes", []), chunks_by_id, question)
    if not quotes and sources:
        chunk = chunks_by_id.get(sources[0]["chunk_id"])
        if chunk:
            quotes.append({
                "chunk_id": chunk["chunk_id"],
                "text": _exact_quote_from_chunk(chunk["text"], question),
                "verified": True,
                "repaired": True,
            })
    return {
        "status": "ok",
        "answer": payload.get("answer", ""),
        "sources": sources,
        "quotes": quotes,
        "retrieval": result,
    }


def answer_rag(question, index, settings=None, history_text="", history_messages=None):
    result = retrieve(index, question, settings, history_text)
    return generate_answer(question, result, history_messages)
