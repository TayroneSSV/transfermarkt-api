from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from app.services.v2.core.client import TransfermarktV2Client
from app.services.v2.core.parsing import (
    clean_text,
    extract_id_from_url,
    get_link_by_url_part,
    normalize_header,
    parse_int,
    soup_from_html,
)
from app.services.v2.core.urls import player_performance_url

STAT_KEY_MAP = {
    "apps": {
        "apps",
        "appearances",
        "spiele",
        "einsaetze",
    },
    "starts": {
        "starts",
        "starting eleven",
        "startelf",
    },
    "minutes": {
        "minutes",
        "minutes played",
        "spielminuten",
        "minuten",
    },
    "goals": {
        "goals",
        "tore",
    },
    "assists": {
        "assists",
        "vorlagen",
    },
    "yellow_cards": {
        "yellow cards",
        "yellow cards cards",
        "gelbe karten",
    },
    "second_yellow_cards": {
        "second yellow cards",
        "second yellow cards cards",
        "gelb rote karten",
    },
    "red_cards": {
        "red cards",
        "red cards cards",
        "rote karten",
    },
}

SEASON_HEADERS = {"season", "saison"}


def _header_from_th(th) -> str:
    return clean_text(th.get("aria-label")) or clean_text(th.get("title")) or clean_text(th.get_text(" ")) or ""


def _match_stat_key(header: str) -> Optional[str]:
    normalized = normalize_header(header)
    for key, variants in STAT_KEY_MAP.items():
        if normalized in variants:
            return key
    return None


def _find_performance_table(soup):
    tables = soup.select("table.items")
    if not tables:
        tables = soup.find_all("table")

    scored_tables = []
    for table in tables:
        header_text = " ".join(_header_from_th(th) for th in table.find_all("th"))
        body_text = clean_text(table.get_text(" "))
        normalized = normalize_header(f"{header_text} {body_text[:500]}")

        score = 0
        if "season" in normalized or "saison" in normalized:
            score += 4
        if "competition" in normalized or "wettbewerb" in normalized:
            score += 3
        if "club" in normalized or "verein" in normalized:
            score += 2
        if "appearances" in normalized or "apps" in normalized or "spiele" in normalized:
            score += 3
        if "minutes" in normalized or "minuten" in normalized:
            score += 2
        if "goals" in normalized or "tore" in normalized:
            score += 1

        scored_tables.append((score, table))

    scored_tables = [item for item in scored_tables if item[0] > 0]
    if not scored_tables:
        return None

    scored_tables.sort(key=lambda item: item[0], reverse=True)
    return scored_tables[0][1]


def _parse_headers(table) -> list[str]:
    header_rows = table.select("thead tr") or table.find_all("tr", recursive=False)[:2]
    headers = []
    for row in header_rows:
        row_headers = [_header_from_th(th) for th in row.find_all("th", recursive=False)]
        if len(row_headers) > len(headers):
            headers = row_headers

    if not headers:
        headers = [_header_from_th(th) for th in table.find_all("th")]

    return [header or f"column_{index + 1}" for index, header in enumerate(headers)]


def _cell_text(cell) -> Optional[str]:
    image_titles = [clean_text(img.get("title")) for img in cell.find_all("img") if clean_text(img.get("title"))]
    text = clean_text(cell.get_text(" "))
    if text:
        return text
    if image_titles:
        return " / ".join(image_titles)
    return None


def _parse_row(cells, headers: list[str]) -> Optional[dict]:
    if len(cells) < 3:
        return None

    raw_cells = {}
    for index, cell in enumerate(cells):
        header = headers[index] if index < len(headers) else f"column_{index + 1}"
        raw_cells[header] = _cell_text(cell)

    season_name = None
    for index, header in enumerate(headers):
        if normalize_header(header) in SEASON_HEADERS and index < len(cells):
            season_name = _cell_text(cells[index])
            break
    if not season_name:
        season_name = _cell_text(cells[0])

    competition_url = competition_name = None
    club_url = club_name = None
    for cell in cells:
        if not competition_url:
            competition_url, competition_name = get_link_by_url_part(cell, ("/wettbewerb/", "/pokalwettbewerb/"))
        if not club_url:
            club_url, club_name = get_link_by_url_part(cell, ("/verein/",))

    parsed = {
        "season_name": season_name,
        "competition_id": extract_id_from_url(competition_url, "wettbewerb")
        or extract_id_from_url(competition_url, "pokalwettbewerb"),
        "competition_name": competition_name,
        "competition_url": competition_url,
        "club_id": extract_id_from_url(club_url, "verein"),
        "club_name": club_name,
        "club_url": club_url,
        "raw_cells": raw_cells,
    }

    for index, header in enumerate(headers):
        key = _match_stat_key(header)
        if key and index < len(cells):
            parsed[key] = parse_int(_cell_text(cells[index]))

    has_minimum_data = parsed.get("season_name") or parsed.get("competition_id") or parsed.get("club_id")
    return parsed if has_minimum_data else None


def _debug_info(response, soup) -> dict:
    tables = soup.find_all("table")
    table_infos = []
    for index, table in enumerate(tables[:10]):
        table_infos.append(
            {
                "index": index,
                "classes": table.get("class") or [],
                "header_text": clean_text(" ".join(_header_from_th(th) for th in table.find_all("th")))[:500],
                "body_preview": clean_text(table.get_text(" "))[:500],
            }
        )

    body_text = clean_text(soup.get_text(" "))
    return {
        "status_code": response.status_code,
        "final_url": response.url,
        "html_length": len(response.text or ""),
        "title": clean_text(soup.title.get_text(" ")) if soup.title else None,
        "table_count": len(tables),
        "table_infos": table_infos,
        "body_preview": body_text[:1000],
    }


class TransfermarktV2PlayerPerformance:
    def __init__(self, tm_id: str, client: Optional[TransfermarktV2Client] = None):
        self.tm_id = tm_id
        self.client = client or TransfermarktV2Client()
        self.source_url = player_performance_url(tm_id)

    def get_performance(self) -> dict:
        response = self.client.get(self.source_url)
        soup = soup_from_html(response.content)
        table = _find_performance_table(soup)
        if table is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "message": f"No performance table found for tm_id={self.tm_id}",
                    "source_url": self.source_url,
                    "debug": _debug_info(response, soup),
                },
            )

        headers = _parse_headers(table)
        rows = []
        for tr in table.select("tbody tr"):
            cells = tr.find_all("td", recursive=False)
            parsed = _parse_row(cells, headers)
            if parsed:
                rows.append(parsed)

        return {
            "tm_id": self.tm_id,
            "source_url": self.source_url,
            "loaded_at": datetime.now(),
            "performance_stats": rows,
        }

    def get_debug(self) -> dict:
        response = self.client.get(self.source_url)
        soup = soup_from_html(response.content)
        return {
            "tm_id": self.tm_id,
            "source_url": self.source_url,
            "loaded_at": datetime.now(),
            "debug": _debug_info(response, soup),
        }
