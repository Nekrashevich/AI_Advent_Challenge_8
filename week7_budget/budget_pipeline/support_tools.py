from __future__ import annotations

import json

from budget_pipeline.config import SUPPORT_JSON


def _load() -> dict:
    return json.loads(SUPPORT_JSON.read_text(encoding="utf-8"))


def list_tickets(status: str = "") -> dict:
    tickets = _load()["tickets"]
    if status:
        tickets = [ticket for ticket in tickets if ticket["status"] == status]
    return {
        "count": len(tickets),
        "tickets": [
            {
                "id": ticket["id"],
                "user_id": ticket["user_id"],
                "status": ticket["status"],
                "subject": ticket["subject"],
                "transaction_ids": ticket["transaction_ids"],
            }
            for ticket in tickets
        ],
    }


def get_ticket(ticket_id: str) -> dict:
    payload = _load()
    ticket = next((item for item in payload["tickets"] if item["id"] == ticket_id), None)
    if ticket is None:
        raise ValueError(f"Тикет не найден: {ticket_id}")
    user = next(item for item in payload["users"] if item["id"] == ticket["user_id"])
    return {"ticket": ticket, "user": user}


def find_user(query: str) -> dict:
    needle = query.strip().lower()
    payload = _load()
    users = [
        user for user in payload["users"]
        if needle in user["id"].lower()
        or needle in user["name"].lower()
        or needle in user["email"].lower()
    ]
    return {
        "count": len(users),
        "users": users,
        "tickets": [ticket for ticket in payload["tickets"] if ticket["user_id"] in {u["id"] for u in users}],
    }

