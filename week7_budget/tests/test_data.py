from decimal import Decimal

from budget_pipeline import data


def test_demo_dataset_profile_and_schema():
    rows = data.load_transactions()
    profile = data.dataset_profile(rows)
    assert profile["rows"] == 314
    assert profile["users"] == {"U-1001": 308, "U-1002": 6}
    assert profile["statuses"] == {"posted": 310, "pending": 2, "failed": 2}
    assert data.validate_transactions(rows) == []


def test_spending_filter_excludes_duplicate_transfer_and_non_posted():
    rows = data.load_transactions()
    expenses = data.posted_expenses(rows, "U-1001")
    ids = {row.transaction_id for row in expenses}
    assert "TRANSACTION-3302" not in ids
    assert "TRANSACTION-3305" not in ids
    assert "TRANSACTION-3306" not in ids
    assert all(row.transaction_type == "expense" for row in expenses)
    assert sum((abs(row.amount_rub or Decimal(0)) for row in expenses), Decimal(0)) == Decimal("994113.26")


def test_tenant_scope_is_applied_before_aggregation():
    rows = data.load_transactions()
    primary = data.monthly_summary(rows, "U-1001")
    secondary = data.monthly_summary(rows, "U-1002")
    assert primary["2026-07"]["income"] == Decimal("95000")
    assert secondary["2026-07"]["income"] == Decimal("118000")
    assert primary["2026-07"]["spend"] != secondary["2026-07"]["spend"]

