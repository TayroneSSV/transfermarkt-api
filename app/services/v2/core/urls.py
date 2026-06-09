TRANSFERMARKT_BASE_URL = "https://www.transfermarkt.com"


def player_performance_url(tm_id: str) -> str:
    """Human Transfermarkt performance page, kept for source reference only."""
    return f"{TRANSFERMARKT_BASE_URL}/-/leistungsdaten/spieler/{tm_id}/saison/ges/plus/1"


def player_performance_ceapi_url(tm_id: str) -> str:
    """Transfermarkt internal JSON endpoint used by the performance page."""
    return f"{TRANSFERMARKT_BASE_URL}/ceapi/performance-game/{tm_id}"
