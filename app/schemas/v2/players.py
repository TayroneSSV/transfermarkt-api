from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class V2PlayerPerformanceRow(BaseModel):
    season_id: Optional[str] = None
    season_name: Optional[str] = None
    competition_id: Optional[str] = None
    competition_name: Optional[str] = None
    competition_url: Optional[str] = None
    club_id: Optional[str] = None
    club_name: Optional[str] = None
    club_url: Optional[str] = None
    apps: Optional[int] = None
    starts: Optional[int] = None
    minutes: Optional[int] = None
    goals: Optional[int] = None
    assists: Optional[int] = None
    yellow_cards: Optional[int] = None
    second_yellow_cards: Optional[int] = None
    red_cards: Optional[int] = None
    raw_cells: dict[str, Any] = Field(default_factory=dict)


class V2PlayerPerformanceResponse(BaseModel):
    tm_id: str
    source_url: str
    loaded_at: datetime = Field(default_factory=datetime.now)
    performance_stats: list[V2PlayerPerformanceRow]
