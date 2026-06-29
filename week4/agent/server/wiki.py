import re
from urllib.parse import quote

import requests

API = "https://ru.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "advent-week4-agent/0.1 (educational MCP demo)"}

_TAGS = re.compile(r"<[^>]+>")


def _clean(text):
    return _TAGS.sub("", text or "").strip()


def wiki_search(query, limit=5):
    response = requests.get(
        API,
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": max(1, min(int(limit), 10)),
            "format": "json",
        },
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    results = []
    for item in response.json()["query"]["search"]:
        title = item["title"]
        results.append({
            "title": title,
            "snippet": _clean(item.get("snippet", "")),
            "url": "https://ru.wikipedia.org/wiki/" + quote(title.replace(" ", "_")),
        })
    return results


def wiki_fetch(title):
    response = requests.get(
        API,
        params={
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "redirects": 1,
            "titles": title,
            "format": "json",
        },
        headers=HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    pages = response.json()["query"]["pages"]
    page = next(iter(pages.values()))
    return {"title": page.get("title", title), "extract": page.get("extract", "")}
