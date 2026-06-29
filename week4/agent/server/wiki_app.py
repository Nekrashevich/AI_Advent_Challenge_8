from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from agent.server.logging import configure_mcp_tool_logging
from agent.server import wiki

configure_mcp_tool_logging()

mcp = FastMCP("advent-wiki")


@mcp.tool(description="Поиск статей в русской Википедии по запросу. Возвращает {results: [{title, snippet, url}]}.")
def wiki_search(
    query: Annotated[str, Field(description="Поисковый запрос")],
    limit: Annotated[int, Field(description="Сколько статей вернуть, 1-10")] = 5,
) -> dict:
    return {"results": wiki.wiki_search(query, limit)}


@mcp.tool(description="Получить полный текст статьи Википедии по точному заголовку. Возвращает {title, extract}.")
def wiki_fetch(
    title: Annotated[str, Field(description="Точный заголовок статьи")],
) -> dict:
    return wiki.wiki_fetch(title)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
