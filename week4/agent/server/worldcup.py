import json
import os
from pathlib import Path

import requests

FOOTBALL_DATA_API = "https://api.football-data.org/v4"
DATA_FILE = Path(__file__).resolve().with_name("worldcup_data.json")
HEADERS = {"User-Agent": "advent-week4-agent/0.1 (educational MCP demo)"}
_PROVIDER_OVERRIDE = None


def _data():
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def _canonical_provider(value):
    value = (value or "").strip().lower()
    if not value:
        return None
    if value == "mock":
        return "mock"
    if value in {"api", "real_api", "football_data", "football-data-api", "football_data_api"}:
        return "football_data"
    raise ValueError("Источник должен быть 'api' или 'mock'")


def _provider():
    return _PROVIDER_OVERRIDE or "football_data"


def _demo_today():
    return os.environ.get("WORLDCUP_DEMO_DATE") or _data().get("demo_today", "2026-06-28")


def _football_data_token():
    return (
        os.environ.get("FOOTBALL_API_KEY")
        or os.environ.get("FOOTBALL_DATA_API_KEY")
        or os.environ.get("FOOTBALL_DATA_TOKEN")
        or ""
    ).strip()


def _auth_headers():
    token = _football_data_token()
    if not token:
        raise RuntimeError("Для WORLDCUP_PROVIDER=football_data укажи FOOTBALL_API_KEY")
    try:
        token.encode("ascii")
    except UnicodeEncodeError as error:
        raise RuntimeError(
            "FOOTBALL_API_KEY должен быть реальным ASCII API-ключом football-data.org, "
            "а не примером вроде 'твой_ключ'."
        ) from error
    headers = dict(HEADERS)
    headers["X-Auth-Token"] = token
    return headers


def _football_get(path, params=None):
    response = requests.get(
        FOOTBALL_DATA_API + path,
        params=params or {},
        headers=_auth_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _normalize_date(value):
    if not value or value == "today":
        return _demo_today()
    return value


def _team_key(value):
    return str(value or "").strip().lower()


def _mock_venue_for(match):
    match_date = match.get("date")
    teams = {_team_key(match.get("home")), _team_key(match.get("away"))}
    if not match_date or "" in teams:
        return {}
    for item in _data()["matches"]:
        if item.get("date") != match_date:
            continue
        if {_team_key(item.get("home")), _team_key(item.get("away"))} == teams:
            return {"city": item.get("city", ""), "stadium": item.get("stadium", "")}
    return {}


def _football_match(row):
    score = row.get("score") or {}
    full_time = score.get("fullTime") or {}
    home_score = full_time.get("home")
    away_score = full_time.get("away")
    match = {
        "id": str(row.get("id")),
        "date": (row.get("utcDate") or "")[:10],
        "kickoff": (row.get("utcDate") or "").replace("Z", ""),
        "home": (row.get("homeTeam") or {}).get("name", ""),
        "away": (row.get("awayTeam") or {}).get("name", ""),
        "stage": row.get("stage") or row.get("group") or "",
        "city": "",
        "stadium": "",
        "status": row.get("status", ""),
        "score": None if home_score is None else f"{home_score}:{away_score}",
    }
    match.update({key: value for key, value in _mock_venue_for(match).items() if value})
    return match


def _mock_matches(date="today", team="", stage=""):
    date = _normalize_date(date)
    team_l = team.lower().strip()
    stage_l = stage.lower().strip()
    matches = []
    for match in _data()["matches"]:
        if date and match["date"] != date:
            continue
        if team_l and team_l not in {match["home"].lower(), match["away"].lower()}:
            continue
        if stage_l and stage_l not in match["stage"].lower():
            continue
        matches.append(match)
    return matches


def wc_matches(date="today", team="", stage=""):
    if _provider() == "football_data":
        date_value = _normalize_date(date)
        payload = _football_get(
            "/competitions/WC/matches",
            {"season": 2026, "dateFrom": date_value, "dateTo": date_value},
        )
        matches = [_football_match(row) for row in payload.get("matches", [])]
        team_l = team.lower().strip()
        stage_l = stage.lower().strip()
        if team_l:
            matches = [m for m in matches if team_l in {m["home"].lower(), m["away"].lower()}]
        if stage_l:
            matches = [m for m in matches if stage_l in m["stage"].lower()]
        return {"provider": "football_data", "date": date_value, "matches": matches}
    return {"provider": "mock", "date": _normalize_date(date), "matches": _mock_matches(date, team, stage)}


def wc_match_detail(match_id):
    if _provider() == "football_data":
        payload = _football_get(f"/matches/{match_id}")
        row = payload.get("match") or payload
        return {"provider": "football_data", "match": _football_match(row)}
    for match in _data()["matches"]:
        if str(match["id"]) == str(match_id):
            return {"provider": "mock", "match": match}
    raise ValueError(f"Матч не найден: {match_id}")


def wc_team_next_match(team):
    team_l = team.lower().strip()
    if _provider() == "football_data":
        payload = _football_get("/competitions/WC/matches", {"season": 2026})
        matches = [_football_match(row) for row in payload.get("matches", [])]
        matches = [m for m in matches if team_l in {m["home"].lower(), m["away"].lower()}]
    else:
        matches = [m for m in _data()["matches"] if team_l in {m["home"].lower(), m["away"].lower()}]
    matches = sorted(matches, key=lambda item: item["kickoff"])
    if not matches:
        raise ValueError(f"Матчи команды не найдены: {team}")
    return {"provider": _provider(), "match": matches[0]}


def wc_group_table(group):
    group = group.strip().upper().removeprefix("GROUP ").strip()
    if _provider() == "football_data":
        payload = _football_get("/competitions/WC/standings", {"season": 2026})
        for standing in payload.get("standings", []):
            if group in str(standing.get("group", "")).upper():
                rows = []
                for row in standing.get("table", []):
                    team = row.get("team") or {}
                    rows.append({
                        "position": row.get("position"),
                        "team": team.get("name", ""),
                        "played": row.get("playedGames"),
                        "points": row.get("points"),
                        "goals_for": row.get("goalsFor"),
                        "goals_against": row.get("goalsAgainst"),
                    })
                return {"provider": "football_data", "group": group, "table": rows}
        return {"provider": "football_data", "group": group, "table": []}
    table = _data().get("groups", {}).get(group, [])
    return {"provider": "mock", "group": group, "table": table}


def wc_bracket(stage="Round of 32"):
    stage_l = (stage or "").lower().strip()
    matches = []
    for match in _data()["matches"]:
        if not stage_l or stage_l in match["stage"].lower():
            matches.append({
                "id": match["id"],
                "pair": f"{match['home']} — {match['away']}",
                "kickoff": match["kickoff"],
                "stage": match["stage"],
            })
    return {"provider": _provider(), "stage": stage or "Round of 32", "matches": matches}

def wc_data_source(mode=""):
    global _PROVIDER_OVERRIDE
    requested = _canonical_provider(mode)
    if requested:
        _PROVIDER_OVERRIDE = requested
    provider = _provider()
    token_present = bool(_football_data_token())
    if provider == "football_data":
        return {
            "provider": "football_data",
            "mode": "real_api",
            "command_mode": "api",
            "source": "football-data.org API",
            "api_url": FOOTBALL_DATA_API,
            "endpoints": [
                "/competitions/WC/matches",
                "/matches/{match_id}",
                "/competitions/WC/standings",
            ],
            "token_configured": token_present,
            "note": "Будут использоваться реальные данные API; нужен FOOTBALL_API_KEY.",
        }
    return {
        "provider": "mock",
        "mode": "mock",
        "command_mode": "mock",
        "source": "local JSON fixture",
        "data_file": str(DATA_FILE),
        "demo_today": _demo_today(),
        "token_configured": token_present,
        "note": "Используются замоканные данные из worldcup_data.json.",
    }
