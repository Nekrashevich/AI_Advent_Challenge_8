from budget_pipeline import data
from budget_pipeline.reporting import _normalize_narrative, _weekly_context_rows, weekly_metrics
from budget_pipeline.retrieval import BM25Index, transaction_documents


def test_refund_pending_is_normalized_as_error_code():
    text = _normalize_narrative("Есть операции со статусом refund_pending.")
    assert "error_code `REFUND_PENDING`" in text
    assert "status=`pending`" in text


def test_weekly_retrieval_does_not_include_old_months():
    rows = data.load_transactions()
    metrics = weekly_metrics(rows)
    context_rows = _weekly_context_rows(rows, "U-1001", metrics)
    hits = BM25Index(transaction_documents(context_rows)).search(
        "недельный отчёт расходы pending duplicate возврат",
        top_k=7,
    )
    assert context_rows
    assert all(metrics["start"] <= row.event_date.isoformat() <= metrics["end"] for row in context_rows)
    assert all(hit.document.id != "transactions:2026-01" for hit in hits)
    assert any(hit.document.id == "transactions:2026-07" for hit in hits)
