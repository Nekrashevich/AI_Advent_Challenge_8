from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from agent.server.logging import configure_mcp_tool_logging
from agent.server import worldcup

configure_mcp_tool_logging()

mcp = FastMCP("advent-worldcup")


@mcp.tool(description="Матчи ЧМ-2026 по дате, команде или стадии. Mock-first, optional football-data.org provider.")
def wc_matches(
    date: Annotated[str, Field(description="Дата YYYY-MM-DD или today")] = "today",
    team: Annotated[str, Field(description="Опционально команда, например Argentina")] = "",
    stage: Annotated[str, Field(description="Опционально стадия, например Round of 32")] = "",
) -> dict:
    return worldcup.wc_matches(date, team, stage)


@mcp.tool(description="Подробности матча ЧМ-2026 по match_id. Возвращает {match}.")
def wc_match_detail(
    match_id: Annotated[str, Field(description="ID матча")],
) -> dict:
    return worldcup.wc_match_detail(match_id)


@mcp.tool(description="Ближайший матч сборной на ЧМ-2026. Возвращает {match}.")
def wc_team_next_match(
    team: Annotated[str, Field(description="Команда, например Argentina")],
) -> dict:
    return worldcup.wc_team_next_match(team)


@mcp.tool(description="Таблица группы ЧМ-2026. Возвращает {group, table}.")
def wc_group_table(
    group: Annotated[str, Field(description="Группа, например A или Group A")],
) -> dict:
    return worldcup.wc_group_table(group)


@mcp.tool(description="Сетка/пары плей-офф ЧМ-2026 для стадии. Возвращает {matches}.")
def wc_bracket(
    stage: Annotated[str, Field(description="Стадия, например Round of 32")] = "Round of 32",
) -> dict:
    return worldcup.wc_bracket(stage)


@mcp.tool(description="Показать или переключить источник данных ЧМ-2026: mode='mock' или mode='api'.")
def wc_data_source(
    mode: Annotated[str, Field(description="Опционально: mock или api")] = "",
) -> dict:
    return worldcup.wc_data_source(mode)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
