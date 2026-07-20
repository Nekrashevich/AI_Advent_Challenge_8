from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from budget_pipeline import project_tools


mcp = FastMCP("week7-budget-project", log_level="WARNING")


@mcp.tool(description="Текущая git-ветка, HEAD, последний коммит и изменённые файлы week7_budget.")
def git_context() -> dict:
    return project_tools.git_context()


@mcp.tool(description="Diff week7_budget: рабочее дерево или диапазон base...head.")
def git_diff(
    base: Annotated[str, Field(description="Начало диапазона")] = "",
    head: Annotated[str, Field(description="Конец диапазона")] = "",
) -> dict:
    return project_tools.git_diff(base, head)


@mcp.tool(description="Список файлов внутри week7_budget по glob-шаблону.")
def list_files(
    pattern: Annotated[str, Field(description="Glob относительно week7_budget")] = "**/*",
    limit: Annotated[int, Field(description="Максимум файлов")] = 200,
) -> dict:
    return project_tools.list_files(pattern, limit)


@mcp.tool(description="Безопасно прочитать до 400 строк файла внутри week7_budget.")
def read_file(
    path: Annotated[str, Field(description="Путь относительно week7_budget")] = "README.md",
    start: Annotated[int, Field(description="Первая строка")] = 1,
    end: Annotated[int, Field(description="Последняя строка, 0 — автоматически")] = 0,
) -> dict:
    return project_tools.read_file(path, start, end)


@mcp.tool(description="Записать воспроизводимый артефакт только в runtime/generated; требуется confirm=true.")
def write_generated_file(
    path: Annotated[str, Field(description="Путь внутри runtime/generated")] = "report.md",
    content: Annotated[str, Field(description="Содержимое файла")] = "",
    confirm: Annotated[bool, Field(description="Явное подтверждение записи")] = False,
) -> dict:
    return project_tools.write_generated_file(path, content, confirm)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

