from __future__ import annotations

from budget_pipeline.llm import LLMResult, ProxyAPIClient
from budget_pipeline.mcp_bridge import McpBridge
from budget_pipeline.retrieval import BM25Index, format_context, project_documents


SYSTEM = """Ты ассистент разработчика проекта трекера расходов.
Отвечай только по фрагментам из блока RAG-контекст. Git и список файлов подтверждают
только состояние и наличие путей, но не содержимое файлов. Не выдумывай детали.
Различай status (posted/pending/failed), transaction_type (expense/income/refund/transfer)
и is_duplicate (булев флаг). Если данных недостаточно, прямо скажи об этом.
Ответ на русском, не более 8 коротких пунктов. В конце напиши `Использованные source id:`
и перечисли только точные id из квадратных скобок RAG-контекста, включая суффикс чанка."""


def _with_verified_sources(answer: str, hits: list) -> str:
    lines = answer.rstrip().splitlines()
    for index, line in enumerate(lines):
        if line.strip().lower().startswith(("использованные source", "использованные источники")):
            lines = lines[:index]
            break
    source_ids = ", ".join(hit.document.id for hit in hits)
    return "\n".join(lines).rstrip() + f"\n\nИспользованные source id: {source_ids}"


def ask_project(
    question: str,
    *,
    client: ProxyAPIClient | None = None,
    bridge: McpBridge | None = None,
) -> dict:
    owned_bridge = bridge is None
    bridge = bridge or McpBridge(["project"])
    if owned_bridge:
        bridge.start()
    try:
        git = bridge.call("project", "git_context")
        files = bridge.call("project", "list_files", {"pattern": "**/*", "limit": 80})
        hits = BM25Index(project_documents()).search(question, top_k=6)
        context = format_context(hits)
        prompt = (
            f"Вопрос: {question}\n\n"
            f"Git: {git}\n"
            f"Файлы проекта (только подтверждение наличия): {files['files']}\n\n"
            f"RAG-контекст:\n{context}"
        )
        llm = (client or ProxyAPIClient()).chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            max_tokens=550,
        )
        return {
            "answer": _with_verified_sources(llm.text, hits),
            "git": git,
            "mcp_status": bridge.status(),
            "hits": hits,
            "llm": llm,
        }
    finally:
        if owned_bridge:
            bridge.stop()


def deterministic_overview() -> str:
    return (
        "Проект состоит из CLI, локального BM25 RAG, двух MCP-серверов, "
        "ProxyAPI-клиента, PR-review pipeline и детерминированного финансового слоя."
    )
