from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.services.clubs.players import TransfermarktClubPlayers
from app.services.competitions.clubs import TransfermarktCompetitionClubs
from app.services.v2.core.client import TransfermarktV2Client
from app.services.v2.players.performance import TransfermarktV2PlayerPerformance


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _season_name_from_id(season_id: Optional[Any]) -> Optional[str]:
    text = _as_str(season_id)
    if not text:
        return None
    try:
        year = int(text)
    except (TypeError, ValueError):
        return text
    return f"{str(year)[-2:]}/{str(year + 1)[-2:]}"


def _safe_max_workers(value: int, default: int = 6, upper_bound: int = 12) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = default
    return max(1, min(upper_bound, numeric))


def _extract_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc)


def _club_players_source_url(club_id: str, season_id: Optional[str]) -> str:
    if season_id:
        return f"https://www.transfermarkt.com/-/kader/verein/{club_id}/saison_id/{season_id}/plus/1"
    return f"https://www.transfermarkt.com/-/kader/verein/{club_id}/plus/1"


class TransfermarktV2CompetitionRoster:
    """Load a whole competition roster in one API call.

    The global import path is: competition -> clubs -> club squads -> optional CEAPI performance.
    Individual performance failures never abort the complete roster response.
    """

    def __init__(
        self,
        *,
        competition_id: str,
        season_id: Optional[str] = None,
        include_performance: bool = True,
        max_workers: int = 6,
    ):
        self.competition_id = str(competition_id).strip()
        self.season_id = _as_str(season_id)
        self.include_performance = bool(include_performance)
        self.max_workers = _safe_max_workers(max_workers)
        self.performance_client = TransfermarktV2Client(timeout_seconds=20, max_retries=1, backoff_seconds=0.5)

    def _load_clubs(self) -> Dict[str, Any]:
        service = TransfermarktCompetitionClubs(
            competition_id=self.competition_id,
            season_id=self.season_id,
        )
        payload = service.get_competition_clubs()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="Competition clubs parser returned invalid payload")
        return payload

    def _load_single_club_players(self, club: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[str]]:
        club_id = _as_str(club.get("id"))
        club_name = _as_str(club.get("name"))
        if not club_id:
            return club, [], "club_without_id"

        try:
            service = TransfermarktClubPlayers(club_id=club_id, season_id=self.season_id)
            payload = service.get_club_players()
            raw_players = payload.get("players", []) if isinstance(payload, dict) else []
            if not isinstance(raw_players, list):
                raw_players = []

            players: List[Dict[str, Any]] = []
            for raw in raw_players:
                if not isinstance(raw, dict):
                    continue
                player_id = _as_str(raw.get("id"))
                if not player_id:
                    continue

                players.append(
                    {
                        "tm_id": player_id,
                        "player_id": player_id,
                        "name": _as_str(raw.get("name")),
                        "position": _as_str(raw.get("position")),
                        "date_of_birth": raw.get("dateOfBirth") or raw.get("date_of_birth"),
                        "age": raw.get("age"),
                        "nationality": raw.get("nationality") if isinstance(raw.get("nationality"), list) else [],
                        "height": raw.get("height"),
                        "foot": _as_str(raw.get("foot")),
                        "joined_on": raw.get("joinedOn") or raw.get("joined_on"),
                        "joined": _as_str(raw.get("joined")),
                        "signed_from": _as_str(raw.get("signedFrom") or raw.get("signed_from")),
                        "contract": raw.get("contract"),
                        "market_value": raw.get("marketValue") or raw.get("market_value"),
                        "status": _as_str(raw.get("status")),
                        "club_id": club_id,
                        "club_name": club_name,
                        "competition_id": self.competition_id,
                        "competition_name": None,
                        "season_id": self.season_id,
                        "season_name": _season_name_from_id(self.season_id),
                        "source_url": _club_players_source_url(club_id, self.season_id),
                        "performance_stats": [],
                        "performance_error": None,
                        "raw_roster_payload": raw,
                    }
                )

            return club, players, None
        except Exception as exc:
            return club, [], _extract_error_message(exc)

    def _load_all_roster_players(self, clubs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        if not clubs:
            return [], [], []

        club_summaries: List[Dict[str, Any]] = []
        all_players: List[Dict[str, Any]] = []
        errors: List[str] = []

        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(clubs)))) as executor:
            futures = [executor.submit(self._load_single_club_players, club) for club in clubs]
            for future in as_completed(futures):
                club, players, error = future.result()
                club_id = _as_str(club.get("id")) or ""
                club_name = _as_str(club.get("name"))

                club_summaries.append(
                    {
                        "id": club_id,
                        "name": club_name,
                        "player_count": len(players),
                        "error": error,
                    }
                )
                all_players.extend(players)
                if error:
                    errors.append(f"club {club_id} {club_name or ''}: {error}")

        club_summaries.sort(key=lambda item: item.get("name") or item.get("id") or "")
        all_players.sort(key=lambda item: ((item.get("club_name") or ""), (item.get("name") or "")))
        return club_summaries, all_players, errors

    def _performance_for_player(self, tm_id: str) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
        try:
            service = TransfermarktV2PlayerPerformance(tm_id=tm_id, client=self.performance_client)
            payload = service.get_performance()
            stats = payload.get("performance_stats", []) if isinstance(payload, dict) else []
            error = payload.get("performance_error") if isinstance(payload, dict) else None
            return tm_id, stats if isinstance(stats, list) else [], _as_str(error)
        except Exception as exc:
            return tm_id, [], _extract_error_message(exc)

    def _attach_performance(self, players: List[Dict[str, Any]]) -> List[str]:
        if not self.include_performance or not players:
            return []

        errors: List[str] = []
        unique_tm_ids = sorted({str(player["tm_id"]) for player in players if player.get("tm_id")})
        performance_by_tm_id: Dict[str, List[Dict[str, Any]]] = {}
        error_by_tm_id: Dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = [executor.submit(self._performance_for_player, tm_id) for tm_id in unique_tm_ids]
            for future in as_completed(futures):
                tm_id, stats, error = future.result()
                performance_by_tm_id[tm_id] = stats
                if error:
                    error_by_tm_id[tm_id] = error
                    errors.append(f"performance {tm_id}: {error}")

        for player in players:
            tm_id = str(player.get("tm_id"))
            player["performance_stats"] = performance_by_tm_id.get(tm_id, [])
            player["performance_error"] = error_by_tm_id.get(tm_id)

        return errors

    def get_roster(self) -> Dict[str, Any]:
        if not self.competition_id:
            raise HTTPException(status_code=400, detail="competition_id is required")

        competition_payload = self._load_clubs()
        competition_name = _as_str(competition_payload.get("name"))
        season_id = _as_str(competition_payload.get("seasonId")) or self.season_id
        if season_id and not self.season_id:
            self.season_id = season_id

        clubs = competition_payload.get("clubs", [])
        if not isinstance(clubs, list):
            clubs = []

        club_summaries, players, errors = self._load_all_roster_players(clubs)

        for player in players:
            player["competition_name"] = competition_name
            player["season_id"] = self.season_id
            player["season_name"] = _season_name_from_id(self.season_id)

        errors.extend(self._attach_performance(players))

        return {
            "competition_id": self.competition_id,
            "competition_name": competition_name,
            "season_id": self.season_id,
            "season_name": _season_name_from_id(self.season_id),
            "loaded_at": datetime.now(),
            "include_performance": self.include_performance,
            "club_count": len(clubs),
            "player_count": len(players),
            "unique_player_count": len({player.get("tm_id") for player in players if player.get("tm_id")}),
            "clubs": club_summaries,
            "players": players,
            "errors": errors,
        }
