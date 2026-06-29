from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from agent.server.logging import configure_mcp_tool_logging
from agent.server import scheduler

configure_mcp_tool_logging()

mcp = FastMCP("advent-scheduler")


@mcp.tool(description="Добавить напоминание. run_at: '+30' (через 30 секунд) или ISO-время '2026-06-26T18:00:00'.")
def remind_add(
    text: Annotated[str, Field(description="Текст напоминания")],
    run_at: Annotated[str, Field(description="Когда сработать: '+<секунды>' или ISO-datetime")],
) -> dict:
    return scheduler.remind_add(text, run_at)


@mcp.tool(description="Список всех напоминаний со статусом. Возвращает {reminders: [...]}.")
def reminders_list() -> dict:
    return {"reminders": scheduler.reminders_list()}


@mcp.tool(description="Агрегированная сводка планировщика: всего/сработало/ожидает напоминаний, тики фона.")
def summary_run() -> dict:
    return scheduler.summary_run()


def main():
    scheduler.start_scheduler()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
