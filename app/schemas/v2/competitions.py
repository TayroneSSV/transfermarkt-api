from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.schemas.v2.players import V2PlayerPerformanceRow


class V2CompetitionRosterClub(BaseModel):
    id: str
    name: Optional[str] = None
    player_count: int = 0
    error: Optional[str] = None


class V2CompetitionRosterPlayer(BaseModel):
    tm_id: str
    player_id: str
    name: Optional[str] = None
    position: Optional[str] = None
    date_of_birth: Optional[Any] = None
    age: Optional[Any] = None
    nationality: list[Any] = Field(default_factory=list)
    height: Optional[Any] = None
    foot: Optional[str] = None
    joined_on: Optional[Any] = None
    joined: Optional[str] = None
    signed_from: Optional[str] = None
    contract: Optional[Any] = None
    market_value: Optional[Any] = None
    status: Optional[str] = None
    club_id: str
    club_name: Optional[str] = None
    competition_id: str
    competition_name: Optional[str] = None
    season_id: Optional[str] = None
    season_name: Optional[str] = None
    source_url: Optional[str] = None
    performance_stats: list[V2PlayerPerformanceRow] = Field(default_factory=list)
    performance_error: Optional[str] = None
    raw_roster_payload: dict[str, Any] = Field(default_factory=dict)


class V2CompetitionRosterResponse(BaseModel):
    competition_id: str
    competition_name: Optional[str] = None
    season_id: Optional[str] = None
    season_name: Optional[str] = None
    loaded_at: datetime = Field(default_factory=datetime.now)
    include_performance: bool = True
    club_count: int = 0
    player_count: int = 0
    unique_player_count: int = 0
    clubs: list[V2CompetitionRosterClub] = Field(default_factory=list)
    players: list[V2CompetitionRosterPlayer] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
