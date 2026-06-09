from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.services.v2.core.client import TransfermarktV2Client
from app.services.v2.core.urls import player_performance_ceapi_url, player_performance_url


def _as_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_dict_value(data: Dict[str, Any], keys: List[str]) -> Optional[Any]:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _season_name_from_id(season_id: Optional[Any]) -> Optional[str]:
    season_int = _as_int(season_id, default=-1)
    if season_int < 0:
        return _as_str(season_id)
    # Normal European season representation. Calendar-year leagues still keep raw season_id.
    return f"{str(season_int)[-2:]}/{str(season_int + 1)[-2:]}"


def _competition_url(competition_id: Optional[str]) -> Optional[str]:
    if not competition_id:
        return None
    return f"https://www.transfermarkt.com/-/startseite/wettbewerb/{competition_id}"


def _club_url(club_id: Optional[str], season_id: Optional[Any]) -> Optional[str]:
    if not club_id:
        return None
    if season_id not in (None, ""):
        return f"https://www.transfermarkt.com/-/spielplan/verein/{club_id}/saison_id/{season_id}"
    return f"https://www.transfermarkt.com/-/startseite/verein/{club_id}"


def _extract_club_name(club_data: Dict[str, Any]) -> Optional[str]:
    value = _first_dict_value(
        club_data,
        [
            "clubName",
            "name",
            "club_name",
            "clubLabel",
            "shortName",
            "clubShortName",
        ],
    )
    return _as_str(value)


def _extract_competition_name(game_info: Dict[str, Any]) -> Optional[str]:
    value = _first_dict_value(
        game_info,
        [
            "competitionName",
            "competition_name",
            "competitionGroupName",
            "competitionGroup",
            "competitionId",
        ],
    )
    return _as_str(value)


def _read_card_stat(card_stats: Dict[str, Any], keys: List[str]) -> int:
    for key in keys:
        if key in card_stats:
            return _as_int(card_stats.get(key))
    return 0


def _parse_appearance(perf: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    game_info = perf.get("gameInformation") or {}
    statistics = perf.get("statistics") or {}
    clubs_info = perf.get("clubsInformation") or {}

    general = statistics.get("generalStatistics") or {}
    if general.get("participationState") not in (None, "played"):
        return None

    playing_time = statistics.get("playingTimeStatistics") or {}
    minutes = _as_int(playing_time.get("playedMinutes"))
    if minutes <= 0 and general.get("participationState") != "played":
        return None

    goal_stats = statistics.get("goalStatistics") or {}
    card_stats = statistics.get("cardStatistics") or {}
    club = clubs_info.get("club") or {}
    opponent = clubs_info.get("opponent") or {}

    season_id = game_info.get("seasonId")
    competition_id = _as_str(game_info.get("competitionId"))
    club_id = _as_str(club.get("clubId"))

    return {
        "season_id": _as_str(season_id),
        "season_name": _season_name_from_id(season_id),
        "competition_id": competition_id,
        "competition_name": _extract_competition_name(game_info),
        "competition_url": _competition_url(competition_id),
        "club_id": club_id,
        "club_name": _extract_club_name(club),
        "club_url": _club_url(club_id, season_id),
        "game_id": _as_str(game_info.get("gameId")),
        "matchday": game_info.get("gameDay"),
        "date": ((game_info.get("date") or {}).get("dateTimeUTC")),
        "opponent_club_id": _as_str(opponent.get("clubId")),
        "opponent_club_name": _extract_club_name(opponent),
        "apps": 1,
        "starts": 1 if playing_time.get("isStarting") else 0,
        "minutes": minutes,
        "goals": _as_int(goal_stats.get("goalsScoredTotal")),
        "assists": _as_int(goal_stats.get("assists")),
        "yellow_cards": _read_card_stat(card_stats, ["yellowCardNet", "yellowCards", "yellowCard"]),
        "second_yellow_cards": _read_card_stat(
            card_stats,
            ["secondYellowCard", "secondYellowCards", "yellowRedCard", "yellowRedCards"],
        ),
        "red_cards": _read_card_stat(card_stats, ["redCard", "redCards"]),
        "raw_cells": {
            "gameInformation": game_info,
            "clubsInformation": clubs_info,
            "statistics": statistics,
        },
    }


def _aggregate_appearances(appearances: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[Optional[str], Optional[str], Optional[str]], Dict[str, Any]] = {}

    for row in appearances:
        key = (row.get("season_id"), row.get("competition_id"), row.get("club_id"))
        if key not in grouped:
            grouped[key] = {
                "season_name": row.get("season_name"),
                "competition_id": row.get("competition_id"),
                "competition_name": row.get("competition_name"),
                "competition_url": row.get("competition_url"),
                "club_id": row.get("club_id"),
                "club_name": row.get("club_name"),
                "club_url": row.get("club_url"),
                "apps": 0,
                "starts": 0,
                "minutes": 0,
                "goals": 0,
                "assists": 0,
                "yellow_cards": 0,
                "second_yellow_cards": 0,
                "red_cards": 0,
                "raw_cells": {
                    "season_id": row.get("season_id"),
                    "source": "ceapi/performance-game aggregated",
                    "game_ids": [],
                },
            }

        target = grouped[key]
        for field in [
            "apps",
            "starts",
            "minutes",
            "goals",
            "assists",
            "yellow_cards",
            "second_yellow_cards",
            "red_cards",
        ]:
            target[field] += _as_int(row.get(field))
        if row.get("game_id"):
            target["raw_cells"]["game_ids"].append(row.get("game_id"))

    def sort_key(item: Dict[str, Any]):
        season_raw = _as_int((item.get("raw_cells") or {}).get("season_id"), default=-1)
        return (season_raw, item.get("competition_id") or "", item.get("club_id") or "")

    return sorted(grouped.values(), key=sort_key, reverse=True)


class TransfermarktV2PlayerPerformance:
    def __init__(self, tm_id: str, client: Optional[TransfermarktV2Client] = None):
        self.tm_id = tm_id
        self.client = client or TransfermarktV2Client()
        self.source_url = player_performance_url(tm_id)
        self.ceapi_url = player_performance_ceapi_url(tm_id)

    def _load_ceapi_payload(self) -> Dict[str, Any]:
        response = self.client.get(self.ceapi_url)
        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Transfermarkt CEAPI returned non-JSON response",
                    "source_url": self.ceapi_url,
                    "error": str(exc),
                    "preview": response.text[:500],
                },
            )

        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=502,
                detail={"message": "Transfermarkt CEAPI returned invalid payload", "source_url": self.ceapi_url},
            )
        if payload.get("success") is False:
            raise HTTPException(
                status_code=404,
                detail={"message": "Transfermarkt CEAPI success=false", "source_url": self.ceapi_url, "payload": payload},
            )
        return payload

    def _parse_payload(self, payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        raw_performances = ((payload.get("data") or {}).get("performance") or [])
        appearances: List[Dict[str, Any]] = []
        for perf in raw_performances:
            if not isinstance(perf, dict):
                continue
            parsed = _parse_appearance(perf)
            if parsed:
                appearances.append(parsed)
        return appearances, _aggregate_appearances(appearances)

    def get_performance(self) -> dict:
        payload = self._load_ceapi_payload()
        appearances, performance_stats = self._parse_payload(payload)

        return {
            "tm_id": self.tm_id,
            "source_url": self.ceapi_url,
            "loaded_at": datetime.now(),
            "performance_stats": performance_stats,
        }

    def get_debug(self) -> dict:
        payload = self._load_ceapi_payload()
        appearances, performance_stats = self._parse_payload(payload)
        raw_performances = ((payload.get("data") or {}).get("performance") or [])

        return {
            "tm_id": self.tm_id,
            "source_url": self.ceapi_url,
            "loaded_at": datetime.now(),
            "debug": {
                "method": "ceapi/performance-game",
                "success": payload.get("success"),
                "raw_performance_count": len(raw_performances),
                "parsed_appearance_count": len(appearances),
                "aggregated_row_count": len(performance_stats),
                "first_raw_keys": list(raw_performances[0].keys()) if raw_performances else [],
                "first_parsed_appearance": appearances[0] if appearances else None,
                "first_aggregated_row": performance_stats[0] if performance_stats else None,
            },
        }
