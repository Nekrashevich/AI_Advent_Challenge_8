"""Generate a deterministic demo CSV with personal expenses."""

import csv
import random
from datetime import date, timedelta

from budget_agent.config import EXPENSES_CSV


CATEGORIES = {
    "groceries": [("Перекресток", "weekly food"), ("ВкусВилл", "healthy food"), ("Лента", "bulk groceries")],
    "restaurants": [("Кофейня", "coffee and snack"), ("Доставка еды", "delivery"), ("Бистро", "lunch outside")],
    "transport": [("Метро", "commute"), ("Такси", "taxi ride"), ("Каршеринг", "car sharing")],
    "subscriptions": [("Музыка", "music subscription"), ("Кино", "streaming"), ("Облако", "cloud storage")],
    "housing": [("Аренда", "rent"), ("Интернет", "home internet")],
    "utilities": [("Электричество", "electricity"), ("Вода", "water bill")],
    "health": [("Аптека", "medicine"), ("Клиника", "doctor visit")],
    "education": [("Курс AI", "learning"), ("Книги", "books")],
    "entertainment": [("Кинотеатр", "movie"), ("Бар", "friends")],
    "travel": [("РЖД", "train tickets"), ("Отель", "short trip")],
}


def _add(rows, d, category, amount, merchant, note):
    rows.append({
        "date": d.isoformat(),
        "category": category,
        "amount": str(int(amount)),
        "merchant": merchant,
        "note": note,
    })


def generate(path=EXPENSES_CSV):
    random.seed(42)
    rows = []
    start = date(2026, 4, 1)
    end = date(2026, 6, 30)
    d = start
    while d <= end:
        if d.day == 1:
            _add(rows, d, "housing", 52000, "Аренда", "monthly rent")
        if d.day in (5, 20):
            _add(rows, d, "utilities", random.choice([3100, 3600, 4200]), "Коммунальные", "regular bill")
        if d.day in (3, 17):
            _add(rows, d, "subscriptions", random.choice([399, 599, 899, 1290]), "Подписка", "recurring service")
        if d.weekday() in (1, 5):
            merchant, note = random.choice(CATEGORIES["groceries"])
            base = random.randint(1800, 5200)
            if d.month == 6:
                base += random.randint(500, 1600)
            _add(rows, d, "groceries", base, merchant, note)
        if d.weekday() in (2, 4):
            merchant, note = random.choice(CATEGORIES["restaurants"])
            base = random.randint(650, 2100)
            if d.month == 6:
                base += random.randint(800, 2200)
                note += "; more office lunches"
            _add(rows, d, "restaurants", base, merchant, note)
        if d.weekday() < 5:
            merchant, note = random.choice(CATEGORIES["transport"])
            base = random.randint(70, 450)
            if d.month == 5 and d.day in (14, 15, 16):
                base += 1200
                note += "; taxi during rain"
            _add(rows, d, "transport", base, merchant, note)
        if d in (date(2026, 4, 12), date(2026, 5, 9), date(2026, 6, 14)):
            merchant, note = random.choice(CATEGORIES["health"])
            _add(rows, d, "health", random.randint(1900, 7400), merchant, note)
        if d in (date(2026, 4, 18), date(2026, 5, 23), date(2026, 6, 11)):
            merchant, note = random.choice(CATEGORIES["education"])
            _add(rows, d, "education", random.randint(1500, 9800), merchant, note)
        if d.weekday() == 6 and random.random() < 0.55:
            merchant, note = random.choice(CATEGORIES["entertainment"])
            base = random.randint(900, 4200)
            if d.month == 6:
                base += random.randint(700, 1800)
            _add(rows, d, "entertainment", base, merchant, note)
        d += timedelta(days=1)

    _add(rows, date(2026, 6, 21), "travel", 18400, "РЖД", "weekend trip tickets")
    _add(rows, date(2026, 6, 22), "travel", 22600, "Отель", "weekend trip hotel")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "category", "amount", "merchant", "note"])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: r["date"]))
    return path, len(rows)


if __name__ == "__main__":
    path, count = generate()
    print(f"generated {count} rows -> {path}")
