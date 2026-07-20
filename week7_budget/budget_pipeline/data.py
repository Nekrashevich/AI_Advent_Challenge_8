from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from budget_pipeline.config import TRANSACTIONS_CSV


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    event_date: date
    posted_at: datetime
    user_id: str
    account_id: str
    transaction_type: str
    status: str
    category: str
    merchant: str
    description: str
    original_amount: Decimal | None
    currency: str
    fx_rate_to_rub: Decimal | None
    amount_rub: Decimal | None
    direction: str
    source: str
    import_batch: str
    external_id: str
    related_transaction_id: str
    is_duplicate: bool
    needs_review: bool
    error_code: str

    @property
    def month(self) -> str:
        return self.event_date.strftime("%Y-%m")


def _decimal(value: str) -> Decimal | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"Некорректное число: {value}") from error


def _bool(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}


def _parse(row: dict[str, str]) -> Transaction:
    return Transaction(
        transaction_id=row["transaction_id"],
        event_date=date.fromisoformat(row["event_date"]),
        posted_at=datetime.fromisoformat(row["posted_at"]),
        user_id=row["user_id"],
        account_id=row["account_id"],
        transaction_type=row["transaction_type"],
        status=row["status"],
        category=row["category"],
        merchant=row["merchant"],
        description=row["description"],
        original_amount=_decimal(row["original_amount"]),
        currency=row["currency"],
        fx_rate_to_rub=_decimal(row["fx_rate_to_rub"]),
        amount_rub=_decimal(row["amount_rub"]),
        direction=row["direction"],
        source=row["source"],
        import_batch=row["import_batch"],
        external_id=row["external_id"],
        related_transaction_id=row["related_transaction_id"],
        is_duplicate=_bool(row["is_duplicate"]),
        needs_review=_bool(row["needs_review"]),
        error_code=row["error_code"],
    )


def load_transactions(path: Path = TRANSACTIONS_CSV) -> list[Transaction]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [_parse(dict(row)) for row in csv.DictReader(handle)]
    if not rows:
        raise ValueError("CSV не содержит транзакций")
    return rows


def validate_transactions(rows: list[Transaction]) -> list[str]:
    issues: list[str] = []
    ids = Counter(row.transaction_id for row in rows)
    for transaction_id, count in ids.items():
        if count > 1:
            issues.append(f"duplicate transaction_id: {transaction_id}")
    for row in rows:
        prefix = row.transaction_id
        if row.transaction_type not in {"expense", "income", "refund", "transfer"}:
            issues.append(f"{prefix}: unknown transaction_type")
        if row.status not in {"posted", "pending", "failed"}:
            issues.append(f"{prefix}: unknown status")
        if row.direction not in {"debit", "credit"}:
            issues.append(f"{prefix}: unknown direction")
        if row.status == "posted" and row.amount_rub is None:
            issues.append(f"{prefix}: posted row has no amount_rub")
        if row.status == "posted" and row.transaction_type == "expense" and (row.amount_rub or 0) > 0:
            issues.append(f"{prefix}: expense amount_rub must be negative")
        if row.status == "posted" and row.transaction_type in {"income", "refund"} and (row.amount_rub or 0) < 0:
            issues.append(f"{prefix}: credit amount_rub must be positive")
        if row.currency != "RUB" and row.status == "posted" and row.fx_rate_to_rub is None:
            issues.append(f"{prefix}: posted FX row has no rate")
    return issues


def posted_expenses(rows: list[Transaction], user_id: str) -> list[Transaction]:
    return [
        row
        for row in rows
        if row.user_id == user_id
        and row.status == "posted"
        and row.transaction_type == "expense"
        and not row.is_duplicate
    ]


def posted_income(rows: list[Transaction], user_id: str) -> list[Transaction]:
    return [
        row
        for row in rows
        if row.user_id == user_id
        and row.status == "posted"
        and row.transaction_type in {"income", "refund"}
        and not row.is_duplicate
    ]


def money(value: Decimal | int | float) -> str:
    amount = Decimal(str(value)).quantize(Decimal("0.01"))
    text = f"{amount:,.2f}".replace(",", " ")
    if text.endswith(".00"):
        text = text[:-3]
    return f"{text} ₽"


def monthly_summary(rows: list[Transaction], user_id: str) -> dict[str, dict]:
    spend = defaultdict(Decimal)
    income = defaultdict(Decimal)
    categories: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in posted_expenses(rows, user_id):
        amount = abs(row.amount_rub or Decimal(0))
        spend[row.month] += amount
        categories[row.month][row.category] += amount
    for row in posted_income(rows, user_id):
        income[row.month] += row.amount_rub or Decimal(0)
    months = sorted(set(spend) | set(income))
    return {
        month: {
            "spend": spend[month],
            "income": income[month],
            "net": income[month] - spend[month],
            "categories": dict(categories[month]),
        }
        for month in months
    }


def review_queue(rows: list[Transaction], user_id: str) -> list[Transaction]:
    return [
        row
        for row in rows
        if row.user_id == user_id
        and (row.needs_review or row.is_duplicate or row.status != "posted" or row.currency != "RUB")
    ]


def dataset_profile(rows: list[Transaction]) -> dict:
    return {
        "rows": len(rows),
        "first_date": min(row.event_date for row in rows).isoformat(),
        "last_date": max(row.event_date for row in rows).isoformat(),
        "users": dict(Counter(row.user_id for row in rows)),
        "types": dict(Counter(row.transaction_type for row in rows)),
        "statuses": dict(Counter(row.status for row in rows)),
        "currencies": dict(Counter(row.currency for row in rows)),
        "review_rows": sum(1 for row in rows if row.needs_review),
        "duplicates": sum(1 for row in rows if row.is_duplicate),
    }

