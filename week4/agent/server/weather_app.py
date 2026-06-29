from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from agent.server.logging import configure_mcp_tool_logging
from agent.server import weather

configure_mcp_tool_logging()

mcp = FastMCP("advent-weather")


@mcp.tool(description="Найти координаты города через Open-Meteo Geocoding API. Возвращает {name, country, latitude, longitude, timezone}.")
def weather_geocode(
    city: Annotated[str, Field(description="Город, например Москва или Mexico City")],
    country: Annotated[str, Field(description="Опциональный фильтр страны или country_code")] = "",
) -> dict:
    return weather.weather_geocode(city, country)


@mcp.tool(description="Получить прогноз Open-Meteo по координатам на 1-7 дней. Возвращает {daily: [...]}.")
def weather_forecast(
    latitude: Annotated[float, Field(description="Широта")],
    longitude: Annotated[float, Field(description="Долгота")],
    days: Annotated[int, Field(description="Количество дней прогноза, 1-7")] = 3,
) -> dict:
    return weather.weather_forecast(latitude, longitude, days)


@mcp.tool(description="Краткая погодная сводка по городу: geocode + forecast одним инструментом.")
def weather_brief(
    city: Annotated[str, Field(description="Город для прогноза")],
    days: Annotated[int, Field(description="Количество дней прогноза, 1-7")] = 3,
    country: Annotated[str, Field(description="Опциональный фильтр страны или country_code")] = "",
) -> dict:
    return weather.weather_brief(city, days, country)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
