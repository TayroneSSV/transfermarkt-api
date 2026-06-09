TRANSFERMARKT_BASE_URL = "https://www.transfermarkt.com"


def player_performance_url(tm_id: str) -> str:
    return f"{TRANSFERMARKT_BASE_URL}/-/leistungsdaten/spieler/{tm_id}/plus/0?saison=ges"
