from fastapi import APIRouter, Query

from app.schemas.v2.competitions import V2CompetitionRosterResponse
from app.services.v2.competitions.roster import TransfermarktV2CompetitionRoster

router = APIRouter()


@router.get("/{competition_id}/roster", response_model=V2CompetitionRosterResponse, response_model_exclude_none=True)
def get_competition_roster(
    competition_id: str,
    season_id: str | None = Query(default=None),
    include_performance: bool = Query(default=True),
    max_workers: int = Query(default=6, ge=1, le=12),
):
    service = TransfermarktV2CompetitionRoster(
        competition_id=competition_id,
        season_id=season_id,
        include_performance=include_performance,
        max_workers=max_workers,
    )
    return service.get_roster()


@router.get("/{competition_id}/rosters", response_model=V2CompetitionRosterResponse, response_model_exclude_none=True)
def get_competition_rosters_alias(
    competition_id: str,
    season_id: str | None = Query(default=None),
    include_performance: bool = Query(default=True),
    max_workers: int = Query(default=6, ge=1, le=12),
):
    service = TransfermarktV2CompetitionRoster(
        competition_id=competition_id,
        season_id=season_id,
        include_performance=include_performance,
        max_workers=max_workers,
    )
    return service.get_roster()
