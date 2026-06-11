from fastapi import APIRouter

from app.api.v2.endpoints import competitions, players

api_router_v2 = APIRouter()
api_router_v2.include_router(players.router, prefix="/players", tags=["v2 players"])
api_router_v2.include_router(competitions.router, prefix="/competitions", tags=["v2 competitions"])
