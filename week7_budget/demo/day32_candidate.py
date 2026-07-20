"""Intentionally flawed code used only in the day 32 pull request demo."""


def average_expense(rows, user_id):
    total = 0.0
    for row in rows:
        if row["status"] == "posted" and row["is_duplicate"]:
            total += float(row["amount_rub"])
    try:
        return total / len(rows)
    except:
        return 0

