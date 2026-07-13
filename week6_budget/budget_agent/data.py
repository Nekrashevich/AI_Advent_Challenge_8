import csv
from collections import defaultdict
from datetime import datetime

from budget_agent.config import EXPENSES_CSV

CATEGORY_LABELS = {
    "groceries": "продукты",
    "restaurants": "кафе и доставка",
    "transport": "транспорт",
    "subscriptions": "подписки",
    "housing": "жилье",
    "utilities": "коммунальные услуги",
    "health": "здоровье",
    "education": "образование",
    "entertainment": "развлечения",
    "travel": "поездки",
}


def category_label(category):
    return CATEGORY_LABELS.get(category, category)


def ensure_data():
    if not EXPENSES_CSV.exists():
        from budget_agent.generate_data import generate
        generate()


def load_expenses():
    ensure_data()
    rows = []
    with EXPENSES_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = dict(row)
            row["amount"] = int(float(row["amount"]))
            row["month"] = row["date"][:7]
            rows.append(row)
    return rows


def money(value):
    return f"{int(round(value)):,}".replace(",", " ") + " ₽"


def totals(rows):
    by_month = defaultdict(int)
    by_category = defaultdict(int)
    by_month_category = defaultdict(lambda: defaultdict(int))
    for row in rows:
        by_month[row["month"]] += row["amount"]
        by_category[row["category"]] += row["amount"]
        by_month_category[row["month"]][row["category"]] += row["amount"]
    return by_month, by_category, by_month_category


def overview_text(rows=None):
    rows = rows or load_expenses()
    by_month, by_category, by_month_category = totals(rows)
    months = sorted(by_month)
    lines = [
        f"Dataset: {len(rows)} transactions from {months[0]} to {months[-1]}.",
        "Monthly totals:",
    ]
    for month in months:
        lines.append(f"- {month}: {money(by_month[month])}")
    lines.append("Category totals:")
    for category, amount in sorted(by_category.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"- {category}: {money(amount)}")
    if len(months) >= 2:
        prev, last = months[-2], months[-1]
        delta = by_month[last] - by_month[prev]
        lines.append(f"Latest month delta: {last} vs {prev}: {money(delta)}.")
        movers = []
        cats = sorted(set(by_month_category[last]) | set(by_month_category[prev]))
        for category in cats:
            movers.append((by_month_category[last][category] - by_month_category[prev][category], category))
        lines.append("Main category changes in latest month:")
        for delta_cat, category in sorted(movers, reverse=True)[:5]:
            lines.append(f"- {category}: {money(delta_cat)}")
    return "\n".join(lines)


def docs_for_retrieval(rows=None):
    rows = rows or load_expenses()
    by_month, by_category, by_month_category = totals(rows)
    docs = []
    months = sorted(by_month)
    if len(months) >= 2:
        prev, last = months[-2], months[-1]
        total_delta = by_month[last] - by_month[prev]
        movers = []
        cats = sorted(set(by_month_category[last]) | set(by_month_category[prev]))
        for category in cats:
            movers.append((by_month_category[last][category] - by_month_category[prev][category], category))
        top_growth = "; ".join(
            f"{category_label(category)}: {money(delta)}"
            for delta, category in sorted(movers, reverse=True)
            if delta > 0
        )
        changes = "; ".join(
            f"{category_label(category)}: {money(delta)}"
            for delta, category in sorted(movers, reverse=True)
        )
        docs.append({
            "id": f"delta:{prev}->{last}",
            "kind": "month_delta",
            "source": "expenses.csv",
            "title": f"Динамика расходов {last} против {prev}",
            "text": (
                f"В {last} расходы выросли относительно {prev} на {money(total_delta)}: "
                f"{money(by_month[last])} против {money(by_month[prev])}. "
                f"Топ причин роста: {top_growth}. "
                f"Изменения по категориям: {changes}. "
                "Главные причины роста нужно искать в самых больших положительных изменениях."
            ),
        })
    for month in sorted(by_month):
        categories = sorted(by_month_category[month].items(), key=lambda item: item[1], reverse=True)
        body = "; ".join(f"{category_label(cat)} {money(amount)}" for cat, amount in categories)
        docs.append({
            "id": f"month:{month}",
            "kind": "month_summary",
            "source": "expenses.csv",
            "title": f"Сводка расходов {month}",
            "text": f"В {month} общие расходы составили {money(by_month[month])}. Категории: {body}.",
        })
    for category, amount in sorted(by_category.items(), key=lambda item: item[1], reverse=True):
        months = "; ".join(
            f"{month} {money(by_month_category[month].get(category, 0))}"
            for month in sorted(by_month)
        )
        docs.append({
            "id": f"category:{category}",
            "kind": "category_summary",
            "source": "expenses.csv",
            "title": f"Сводка категории {category_label(category)}",
            "text": (
                f"Категория {category_label(category)}: всего {money(amount)}. "
                f"Разбивка по месяцам: {months}."
            ),
        })
    for index, row in enumerate(rows):
        if row["amount"] >= 4500 or row["category"] in ("travel", "housing", "education", "health"):
            docs.append({
                "id": f"tx:{index:03}",
                "kind": "transaction",
                "source": "expenses.csv",
                "title": f"{row['date']} {category_label(row['category'])} {row['merchant']}",
                "text": (
                    f"Транзакция {row['date']}: категория {category_label(row['category'])}, "
                    f"сумма {money(row['amount'])}, продавец {row['merchant']}, примечание: {row['note']}."
                ),
            })
    return docs


def month_name(month):
    return datetime.strptime(month + "-01", "%Y-%m-%d").strftime("%B %Y")
