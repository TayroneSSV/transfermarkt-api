from fastapi import APIRouter

from app.schemas.v2.players import V2PlayerPerformanceResponse
from app.services.v2.players.performance import TransfermarktV2PlayerPerformance

router = APIRouter()


@router.get("/{tm_id}/performance", response_model=V2PlayerPerformanceResponse, response_model_exclude_none=True)
def get_player_performance(tm_id: str):
    service = TransfermarktV2PlayerPerformance(tm_id=tm_id)
    return service.get_performance()


@router.get("/{tm_id}/performance-debug")
def get_player_performance_debug(tm_id: str):
    service = TransfermarktV2PlayerPerformance(tm_id=tm_id)
    return service.get_debug()
