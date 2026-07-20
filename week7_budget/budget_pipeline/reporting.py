from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from budget_pipeline import data, project_tools
from budget_pipeline.config import PRIMARY_USER_ID
from budget_pipeline.llm import ProxyAPIClient, ProxyAPIError
from budget_pipeline.retrieval import BM25Index, format_context, project_documents, transaction_documents


def weekly_metrics(rows: list[data.Transaction], user_id: str = PRIMARY_USER_ID) -> dict:
    user_rows = [row for row in rows if row.user_id == user_id]
    end = max(row.event_date for row in user_rows)
    start = end - timedelta(days=6)
    period = [row for row in user_rows if start <= row.event_date <= end]
    spend_rows = data.posted_expenses(period, user_id)
    income_rows = data.posted_income(period, user_id)
    categories = defaultdict(Decimal)
    for row in spend_rows:
        categories[row.category] += abs(row.amount_rub or Decimal(0))
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "spend": sum((abs(row.amount_rub or Decimal(0)) for row in spend_rows), Decimal(0)),
        "income": sum((row.amount_rub or Decimal(0) for row in income_rows), Decimal(0)),
        "categories": dict(sorted(categories.items(), key=lambda item: item[1], reverse=True)),
        "review_count": len(data.review_queue(period, user_id)),
        "excluded_pending": sum(1 for row in period if row.status == "pending"),
        "excluded_failed": sum(1 for row in period if row.status == "failed"),
        "excluded_duplicates": sum(1 for row in period if row.is_duplicate),
    }


def _render(metrics: dict, narrative: str) -> str:
    categories = "\n".join(
        f"- {category}: {data.money(amount)}" for category, amount in metrics["categories"].items()
    ) or "- Нет подтверждённых расходов"
    return f"""# Weekly budget report

Period: {metrics['start']} — {metrics['end']}

## Verified metrics

- Posted spending: {data.money(metrics['spend'])}
- Posted income/refunds: {data.money(metrics['income'])}
- Items requiring attention: {metrics['review_count']}
- Excluded pending: {metrics['excluded_pending']}
- Excluded failed: {metrics['excluded_failed']}
- Excluded duplicates: {metrics['excluded_duplicates']}

## Categories

{categories}

## AI interpretation

{narrative}

## Human-in-the-loop

This is a draft. Review it before sending or changing a budget.
"""


def _normalize_narrative(narrative: str) -> str:
    return re.sub(
        r"(?i)(?:status|статус(?:ом|ах|а|ы|е)?)\s+[`\"']?refund_pending[`\"']?",
        "error_code `REFUND_PENDING` при status=`pending`",
        narrative,
    )


def _weekly_context_rows(
    rows: list[data.Transaction],
    user_id: str,
    metrics: dict,
) -> list[data.Transaction]:
    start = date.fromisoformat(metrics["start"])
    end = date.fromisoformat(metrics["end"])
    return [
        row for row in rows
        if row.user_id == user_id and start <= row.event_date <= end
    ]


def run_weekly_pipeline(*, client: ProxyAPIClient | None = None, user_id: str = PRIMARY_USER_ID) -> dict:
    rows = data.load_transactions()
    issues = data.validate_transactions(rows)
    metrics = weekly_metrics(rows, user_id)
    context_rows = _weekly_context_rows(rows, user_id, metrics)
    query = "недельный отчёт расходы аномалии pending duplicate возврат рекомендации"
    hits = BM25Index(project_documents() + transaction_documents(context_rows)).search(query, top_k=7)
    prompt = (
        f"Проверенные метрики: {metrics}. Нарушения схемы: {issues or 'нет'}.\n\n"
        f"Контекст:\n{format_context(hits)}\n\n"
        "Допустимые status: posted, pending, failed. REFUND_PENDING — это error_code, "
        "а не status. Дай 3 кратких вывода и 3 безопасных действия. "
        "Не меняй и не пересчитывай суммы."
    )
    try:
        llm = (client or ProxyAPIClient()).chat(
            [
                {"role": "system", "content": "Ты финансовый аналитик. Не выдавай инвестиционные или кредитные советы."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=480,
        )
        narrative = _normalize_narrative(llm.text)
        mode = "proxyapi"
    except ProxyAPIError as error:
        llm = None
        mode = "deterministic-fallback"
        narrative = (
            "Генерация недоступна. Проверьте операции из очереди review; "
            "pending, failed и duplicate уже исключены из финансовых итогов."
        )
        fallback_error = str(error)
    report = _render(metrics, narrative)
    written = project_tools.write_generated_file("weekly-budget-report.md", report, confirm=True)
    result = {
        "metrics": metrics,
        "validation_issues": issues,
        "hits": hits,
        "mode": mode,
        "written": written,
        "llm": llm,
    }
    if mode != "proxyapi":
        result["fallback_error"] = fallback_error
    return result
