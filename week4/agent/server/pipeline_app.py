from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from agent.server.logging import configure_mcp_tool_logging
from agent.server import pipeline

configure_mcp_tool_logging()

mcp = FastMCP("advent-pipeline")


@mcp.tool(description="Сжать текст в краткое саммари на русском (4-6 пунктов). Возвращает {summary}.")
def summarize(
    text: Annotated[str, Field(description="Исходный текст для суммаризации")],
) -> dict:
    return {"summary": pipeline.summarize(text)}


@mcp.tool(description="Сохранить текст в файл в каталоге store. Возвращает {path}.")
def save_to_file(
    name: Annotated[str, Field(description="Имя файла без пути")],
    content: Annotated[str, Field(description="Содержимое файла")],
) -> dict:
    return {"path": pipeline.save_to_file(name, content)}


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
