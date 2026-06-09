from fastapi import APIRouter

from app.api.endpoints import clubs, competitions, players
from app.api.v2.api import api_router_v2

api_router = APIRouter()
api_router.include_router(competitions.router, prefix="/competitions", tags=["competitions"])
api_router.include_router(clubs.router, prefix="/clubs", tags=["clubs"])
api_router.include_router(players.router, prefix="/players", tags=["players"])

api_router.include_router(api_router_v2, prefix="/v2")
