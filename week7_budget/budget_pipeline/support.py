from __future__ import annotations

import json

from budget_pipeline import data
from budget_pipeline.llm import ProxyAPIClient
from budget_pipeline.mcp_bridge import McpBridge
from budget_pipeline.retrieval import BM25Index, Document, format_context, project_documents


SYSTEM = """Ты специалист поддержки трекера расходов. Используй только карточку тикета,
профиль пользователя, связанные транзакции, политику ответа и FAQ. Не предлагай удалять,
скрывать или редактировать исходные операции. Не обещай возврат или изменение данных.
Не утверждай, что операция автоматически изменит баланс: можно говорить только, что
подтверждённый status=posted позволяет учесть возврат в следующих расчётах отчёта.
Если duplicate уже исключён из итогов, прямо сообщи это и предложи только ручную проверку;
эскалируй тикет, если показанный итог всё равно неверен. Различай status и error_code.
Отделяй подтверждённые факты от предположений. Ответь по-русски в JSON:
{"diagnosis":"...","reply":"...","next_action":"...","sources":["..."]}."""


def _transaction_context(rows: list[data.Transaction]) -> list[Document]:
    return [
        Document(
            id=f"ticket-transaction:{row.transaction_id}",
            title=f"Связанная операция {row.transaction_id}",
            text=(
                f"transaction_id={row.transaction_id}; user_id={row.user_id}; "
                f"date={row.event_date}; type={row.transaction_type}; "
                f"status={row.status}; amount_rub={row.amount_rub}; category={row.category}; "
                f"duplicate={row.is_duplicate}; needs_review={row.needs_review}; "
                f"error_code={row.error_code}; related={row.related_transaction_id or 'none'}"
            ),
            source="data/transactions.csv",
            kind="data",
        )
        for row in rows
    ]


def _support_policy(rows: list[data.Transaction]) -> str:
    if any(row.is_duplicate for row in rows):
        return (
            "Повторная строка с is_duplicate=true уже исключена из финансовых итогов. "
            "Не советуй удалять или скрывать её. Попроси проверить итог и передать тикет "
            "инженеру только если сумма всё ещё неверна."
        )
    if any(row.transaction_type == "refund" and row.status == "pending" for row in rows):
        return (
            "Возврат имеет status=pending и error_code=REFUND_PENDING; это не отдельный статус. "
            "Он может быть учтён как подтверждённый возврат только после status=posted. "
            "Не обещай автоматическое изменение баланса. Предложи дождаться подтверждения."
        )
    if any(row.error_code == "FX_RATE_MISSING" for row in rows):
        return (
            "Операция имеет status=failed и error_code=FX_RATE_MISSING. Она не входит в расходы "
            "до появления курса и успешной повторной обработки импорта."
        )
    return "Не предлагай изменять исходные операции; при необходимости передай тикет на ручную проверку."


def _apply_support_guardrails(payload: dict, rows: list[data.Transaction]) -> dict:
    answer = dict(payload)
    combined = " ".join(str(answer.get(key, "")) for key in ("reply", "next_action")).lower()
    if any(row.is_duplicate for row in rows) and any(word in combined for word in ("удал", "скры")):
        answer["reply"] = (
            "Повторная операция уже помечена как дубликат и исключена из финансовых итогов. "
            "Пожалуйста, проверьте отображаемую итоговую сумму."
        )
        answer["next_action"] = (
            "Оставить исходные операции без изменений и выполнить ручную проверку. "
            "Если итог по-прежнему неверен, передать тикет инженеру."
        )
    pending_refund = next(
        (row for row in rows if row.transaction_type == "refund" and row.status == "pending"),
        None,
    )
    if pending_refund and any(word in combined for word in ("баланс", "автомат", "гарантир")):
        amount = data.money(pending_refund.amount_rub or 0)
        answer["reply"] = (
            f"Возврат {amount} имеет статус pending и пока не входит в подтверждённые доходы. "
            "После подтверждения банком и получения status=posted он сможет учитываться "
            "в следующих расчётах отчёта."
        )
        answer["next_action"] = (
            "Дождаться подтверждения банка. Если статус не обновится в ожидаемый срок, "
            "передать тикет на ручную проверку."
        )
    return answer


def answer_ticket(
    ticket_id: str,
    *,
    client: ProxyAPIClient | None = None,
    bridge: McpBridge | None = None,
) -> dict:
    owned_bridge = bridge is None
    bridge = bridge or McpBridge(["support"])
    if owned_bridge:
        bridge.start()
    try:
        card = bridge.call("support", "get_ticket", {"ticket_id": ticket_id})
        ticket = card["ticket"]
        selected = set(ticket["transaction_ids"])
        linked_rows = [row for row in data.load_transactions() if row.transaction_id in selected]
        transaction_docs = _transaction_context(linked_rows)
        faq_docs = [doc for doc in project_documents() if doc.source == "docs/faq.md"]
        corpus = faq_docs + transaction_docs
        query = (
            ticket["subject"] + " "
            + " ".join(ticket["transaction_ids"]) + " "
            + " ".join(message["text"] for message in ticket["messages"])
            + " " + " ".join(document.text for document in transaction_docs)
        )
        hits = BM25Index(corpus).search(query, top_k=7)
        prompt = (
            f"Карточка тикета и пользователь:\n{json.dumps(card, ensure_ascii=False, indent=2)}\n\n"
            f"Политика ответа:\n{_support_policy(linked_rows)}\n\n"
            f"RAG-контекст:\n{format_context(hits)}"
        )
        payload, llm = (client or ProxyAPIClient()).chat_json(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
            max_tokens=550,
        )
        payload = _apply_support_guardrails(payload, linked_rows)
        return {"card": card, "answer": payload, "hits": hits, "llm": llm, "mcp_status": bridge.status()}
    finally:
        if owned_bridge:
            bridge.stop()


def deterministic_ticket_answer(ticket_id: str) -> dict:
    card = __import__("budget_pipeline.support_tools", fromlist=["get_ticket"]).get_ticket(ticket_id)
    error_codes = {
        "ADVENT-101": "Обнаружен повторный импорт одной операции. Дубликат исключается из отчётов.",
        "ADVENT-102": "Возврат имеет статус pending и ещё не должен учитываться как зачисленный.",
        "ADVENT-103": "Для валютной операции отсутствует курс, поэтому импорт помечен failed.",
    }
    return {"card": card, "answer": {"diagnosis": error_codes.get(ticket_id, "Нужна ручная проверка")}}
