import requests

GEOCODING_API = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_API = "https://api.open-meteo.com/v1/forecast"
HEADERS = {"User-Agent": "advent-week4-agent/0.1 (educational MCP demo)"}

WEATHER_CODES = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "изморозь и туман",
    51: "слабая морось",
    53: "морось",
    55: "сильная морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    80: "ливень",
    81: "сильный ливень",
    82: "очень сильный ливень",
    95: "гроза",
    96: "гроза с градом",
    99: "сильная гроза с градом",
}


def _clamp_days(days):
    return max(1, min(int(days), 7))


def _summary(code):
    return WEATHER_CODES.get(int(code), f"weather_code={code}")


def weather_geocode(city, country=""):
    response = requests.get(
        GEOCODING_API,
        params={"name": city, "count": 10, "language": "ru", "format": "json"},
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    if not results:
        raise ValueError(f"Город не найден: {city}")

    selected = results[0]
    if country:
        lowered = country.lower()
        for item in results:
            if lowered in {str(item.get("country", "")).lower(), str(item.get("country_code", "")).lower()}:
                selected = item
                break

    return {
        "name": selected.get("name", city),
        "country": selected.get("country", ""),
        "country_code": selected.get("country_code", ""),
        "latitude": selected["latitude"],
        "longitude": selected["longitude"],
        "timezone": selected.get("timezone", "auto"),
    }


def weather_forecast(latitude, longitude, days=3):
    days = _clamp_days(days)
    response = requests.get(
        FORECAST_API,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": ",".join([
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_probability_max",
                "weather_code",
                "wind_speed_10m_max",
            ]),
            "timezone": "auto",
            "forecast_days": days,
        },
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    daily = payload.get("daily", {})
    rows = []
    for index, day in enumerate(daily.get("time", [])):
        code = daily.get("weather_code", [None] * days)[index]
        rows.append({
            "date": day,
            "temp_min": daily.get("temperature_2m_min", [None] * days)[index],
            "temp_max": daily.get("temperature_2m_max", [None] * days)[index],
            "precipitation_probability": daily.get("precipitation_probability_max", [None] * days)[index],
            "wind_speed": daily.get("wind_speed_10m_max", [None] * days)[index],
            "weather_code": code,
            "summary": _summary(code) if code is not None else "нет данных",
        })
    return {
        "latitude": payload.get("latitude", latitude),
        "longitude": payload.get("longitude", longitude),
        "timezone": payload.get("timezone", "auto"),
        "daily": rows,
    }


def weather_brief(city, days=3, country=""):
    location = weather_geocode(city, country)
    forecast = weather_forecast(location["latitude"], location["longitude"], days)
    lines = []
    for row in forecast["daily"]:
        lines.append(
            f"{row['date']}: {row['temp_min']}..{row['temp_max']} C, "
            f"{row['summary']}, дождь {row['precipitation_probability']}%, "
            f"ветер до {row['wind_speed']} км/ч"
        )
    return {
        "location": location,
        "timezone": forecast["timezone"],
        "daily": forecast["daily"],
        "brief": "\n".join(lines),
    }
