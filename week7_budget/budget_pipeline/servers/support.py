from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from budget_pipeline import support_tools


mcp = FastMCP("week7-budget-support", log_level="WARNING")


@mcp.tool(description="Список синтетических тикетов поддержки, при необходимости по статусу.")
def list_tickets(
    status: Annotated[str, Field(description="open, closed или пусто")] = "",
) -> dict:
    return support_tools.list_tickets(status)


@mcp.tool(description="Карточка тикета вместе с контекстом пользователя и связанными transaction_id.")
def get_ticket(
    ticket_id: Annotated[str, Field(description="Например ADVENT-101")] = "",
) -> dict:
    return support_tools.get_ticket(ticket_id)


@mcp.tool(description="Поиск пользователя по id, имени или email.")
def find_user(
    query: Annotated[str, Field(description="Строка поиска")] = "",
) -> dict:
    return support_tools.find_user(query)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
