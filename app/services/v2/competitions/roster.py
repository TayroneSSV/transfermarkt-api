from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import re
from time import sleep
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag
from fastapi import HTTPException

from app.services.v2.core.client import TransfermarktV2Client
from app.services.v2.players.performance import TransfermarktV2PlayerPerformance

TRANSFERMARKT_WEB_BASE_URL = "https://www.transfermarkt.com"

# Wichtig: Transfermarkt akzeptiert fuer viele Seiten keinen '-' Platzhalter mehr.
# Der Slug vor der Route muss realistisch sein, die eindeutige Wahrheit bleibt aber competition_id.
COMPETITION_SLUG_BY_ID: Dict[str, str] = {
    "L1": "bundesliga",
    "L2": "2-bundesliga",
    "L3": "3-liga",
    "RLB3": "regionalliga-bayern",
    "RLW3": "regionalliga-west",
    "RLSW": "regionalliga-sudwest",
    "RLN3": "regionalliga-nord",
    "RLN4": "regionalliga-nordost",
    "A1": "bundesliga",
    "A2": "2-liga",
    "C1": "super-league",
    "C2": "challenge-league",
    "NL1": "eredivisie",
    "NL2": "eerste-divisie",
    "BE1": "jupiler-pro-league",
    "BE2": "challenger-pro-league",
    "DK1": "superligaen",
    "SE1": "allsvenskan",
    "NO1": "eliteserien",
    "FI1": "veikkausliiga",
    "PL1": "ekstraklasa",
    "TS1": "fortuna-liga",
    "UNG1": "nemzeti-bajnoksag",
    "RO1": "superliga",
    "KR1": "supersport-hnl",
    "SER1": "super-liga-srbije",
    "SLO1": "prva-liga",
    "GB2": "championship",
    "FR2": "ligue-2",
    "IT2": "serie-b",
    "ES2": "laliga2",
    "PO1": "liga-portugal",
    "TR1": "super-lig",
}


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).replace("\xa0", " ").split()).strip()
    return text or None


def _as_str(value: Any) -> Optional[str]:
    return _clean_text(value)


def _extract_id_from_href(href: Optional[str], marker: str) -> Optional[str]:
    if not href:
        return None
    match = re.search(r"/" + re.escape(marker) + r"/(\d+)", href)
    return match.group(1) if match else None


def _extract_season_from_href(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    match = re.search(r"/saison_id/(\d+)", href)
    return match.group(1) if match else None


def _season_name_from_id(season_id: Optional[Any]) -> Optional[str]:
    text = _as_str(season_id)
    if not text:
        return None
    try:
        year = int(text)
    except (TypeError, ValueError):
        return text
    return f"{str(year)[-2:]}/{str(year + 1)[-2:]}"


def _safe_max_workers(value: int, default: int = 6, upper_bound: int = 10) -> int:
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = default
    return max(1, min(upper_bound, numeric))


def _slugify(value: Optional[str]) -> str:
    text = (value or "club").lower().strip()
    replacements = {
        "ä": "a",
        "ö": "o",
        "ü": "u",
        "ß": "ss",
        "é": "e",
        "è": "e",
        "á": "a",
        "à": "a",
        "ó": "o",
        "ò": "o",
        "í": "i",
        "ì": "i",
        "ú": "u",
        "ù": "u",
        "ç": "c",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "club"


def _competition_url_candidates(competition_id: str, season_id: Optional[str]) -> List[str]:
    comp = str(competition_id or "").strip()
    season = str(season_id or "").strip() or None
    slug = COMPETITION_SLUG_BY_ID.get(comp, comp.lower())

    # Wichtig: Render bekam auf .de und auf alte /-/ URLs 405.
    # Die funktionierende öffentliche Transfermarkt-Struktur ist aktuell .com + echter Wettbewerbsslug,
    # z. B. https://www.transfermarkt.com/2-bundesliga/startseite/wettbewerb/L2
    hosts = [
        "https://www.transfermarkt.com",
        "https://www.transfermarkt.us",
        "https://www.transfermarkt.co.uk",
    ]

    urls: List[str] = []
    for host in hosts:
        # Current-season Seite zuerst. Für Saison 2025 ist das bei 25/26 die stabilste URL.
        urls.append(f"{host}/{slug}/startseite/wettbewerb/{comp}")
        if season:
            urls.append(f"{host}/{slug}/startseite/wettbewerb/{comp}/saison_id/{season}")
            urls.append(f"{host}/{slug}/startseite/wettbewerb/{comp}?saison_id={season}")
            urls.append(f"{host}/{slug}/startseite/wettbewerb/{comp}/plus/1?saison_id={season}")

    deduped: List[str] = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Referer": f"{TRANSFERMARKT_WEB_BASE_URL}/",
    }


class _WebClient:
    def __init__(self, timeout_seconds: int = 25, max_retries: int = 2):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(_headers())

    def get_soup(self, url: str) -> BeautifulSoup:
        last_error: Optional[str] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=self.timeout_seconds, allow_redirects=True)
                if response.status_code == 200:
                    return BeautifulSoup(response.text, "html.parser")
                last_error = f"{response.status_code} {response.reason} for {response.url}"
                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    sleep(1.5 * attempt)
                    continue
                break
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt < self.max_retries:
                    sleep(1.5 * attempt)
                    continue
        raise HTTPException(status_code=502, detail=f"Transfermarkt web request failed: {last_error}")


def _competition_name_from_soup(soup: BeautifulSoup) -> Optional[str]:
    headline = soup.select_one("div.data-header__headline-container h1") or soup.select_one("h1")
    return _clean_text(headline.get_text(" ")) if headline else None


def _parse_competition_clubs(soup: BeautifulSoup, season_id: Optional[str]) -> List[Dict[str, Any]]:
    links = soup.select('td.hauptlink.no-border-links a[href*="/startseite/verein/"]')
    if not links:
        links = soup.select('a[href*="/startseite/verein/"]')

    clubs: List[Dict[str, Any]] = []
    seen = set()
    for link in links:
        href = link.get("href")
        club_id = _extract_id_from_href(href, "verein")
        if not club_id or club_id in seen:
            continue
        name = _clean_text(link.get("title")) or _clean_text(link.get_text(" "))
        if not name:
            continue
        absolute = urljoin(TRANSFERMARKT_WEB_BASE_URL, href)
        club_season = _extract_season_from_href(href) or season_id
        roster_url = absolute.replace("/startseite/", "/kader/")
        if "/plus/1" not in roster_url:
            roster_url = roster_url.rstrip("/") + "/plus/1"
        if club_season and "/saison_id/" not in roster_url:
            roster_url = roster_url.rstrip("/") + f"/saison_id/{club_season}/plus/1"
        # Normalisieren, falls plus/1 vor saison_id durch alte Links verrutschen sollte.
        roster_url = re.sub(r"/plus/1/saison_id/(\d+)", r"/saison_id/\1/plus/1", roster_url)

        seen.add(club_id)
        clubs.append(
            {
                "id": club_id,
                "name": name,
                "source_url": absolute,
                "roster_url": roster_url,
            }
        )
    return clubs


def _cell_text(cells: List[Tag], index: int) -> Optional[str]:
    if index >= len(cells):
        return None
    return _clean_text(cells[index].get_text(" "))


def _parse_dob_age(text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not text:
        return None, None
    dob_match = re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", text)
    age_match = re.search(r"\((\d+)\)", text)
    return (dob_match.group(0) if dob_match else None, age_match.group(1) if age_match else None)


def _market_value_from_row(row: Tag, cells: List[Tag]) -> Optional[str]:
    cell = row.select_one("td.rechts.hauptlink")
    if cell:
        value = _clean_text(cell.get_text(" "))
        if value:
            return value
    return _cell_text(cells, len(cells) - 1) if cells else None


def _player_position_from_cell(pos_cell: Optional[Tag], name: Optional[str]) -> Optional[str]:
    if not pos_cell:
        return None
    rows = pos_cell.select("tr")
    if len(rows) >= 2:
        return _clean_text(rows[1].get_text(" "))
    full_text = _clean_text(pos_cell.get_text(" "))
    if full_text and name:
        return _clean_text(full_text.replace(name, "", 1))
    return full_text


def _parse_club_players(soup: BeautifulSoup, club: Dict[str, Any], competition_id: str, competition_name: Optional[str], season_id: Optional[str]) -> List[Dict[str, Any]]:
    rows = soup.select("#yw1 table.items tbody > tr")
    if not rows:
        rows = soup.select("table.items tbody > tr")

    players: List[Dict[str, Any]] = []
    seen = set()
    roster_url = club.get("roster_url")
    for row in rows:
        player_link = row.select_one('a[href*="/profil/spieler/"]')
        if not player_link:
            continue
        href = player_link.get("href")
        tm_id = _extract_id_from_href(href, "spieler")
        if not tm_id or tm_id in seen:
            continue

        name = _clean_text(player_link.get("title")) or _clean_text(player_link.get_text(" "))
        cells = row.find_all("td", recursive=False)
        pos_cell = row.select_one("td.posrela")
        position = _player_position_from_cell(pos_cell, name)
        dob, age = _parse_dob_age(_cell_text(cells, 2))

        nationalities: List[str] = []
        if len(cells) > 3:
            for image in cells[3].select("img.flaggenrahmen[title]"):
                title = _clean_text(image.get("title"))
                if title and title not in nationalities:
                    nationalities.append(title)

        signed_from = None
        if len(cells) > 7:
            signed_img = cells[7].select_one("img[title]")
            signed_from = _clean_text(signed_img.get("title")) if signed_img else _clean_text(cells[7].get_text(" "))

        player_payload = {
            "tm_id": tm_id,
            "player_id": tm_id,
            "name": name,
            "position": position,
            "date_of_birth": dob,
            "age": age,
            "nationality": nationalities,
            "height": _cell_text(cells, 4) if len(cells) >= 10 else None,
            "foot": _cell_text(cells, 5) if len(cells) >= 10 else None,
            "joined_on": _cell_text(cells, 6) if len(cells) >= 10 else None,
            "joined": signed_from,
            "signed_from": signed_from,
            "contract": _cell_text(cells, 8) if len(cells) >= 10 else None,
            "market_value": _market_value_from_row(row, cells),
            "status": None,
            "club_id": str(club.get("id")),
            "club_name": club.get("name"),
            "competition_id": competition_id,
            "competition_name": competition_name,
            "season_id": season_id,
            "season_name": _season_name_from_id(season_id),
            "source_url": roster_url,
            "performance_stats": [],
            "performance_error": None,
            "raw_roster_payload": {
                "source": "transfermarkt.com club roster detail page",
                "player_url": urljoin(TRANSFERMARKT_WEB_BASE_URL, href),
                "jersey_number": _cell_text(cells, 0),
                "row_text": _clean_text(row.get_text(" ")),
            },
        }
        seen.add(tm_id)
        players.append(player_payload)
    return players


def _extract_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    return str(exc)


class TransfermarktV2CompetitionRoster:
    def __init__(
        self,
        *,
        competition_id: str,
        season_id: Optional[str] = None,
        include_performance: bool = True,
        max_workers: int = 6,
    ):
        self.competition_id = str(competition_id or "").strip()
        self.season_id = _as_str(season_id)
        self.include_performance = bool(include_performance)
        self.max_workers = _safe_max_workers(max_workers)
        self.web_client = _WebClient(timeout_seconds=30, max_retries=2)
        self.performance_client = TransfermarktV2Client(timeout_seconds=20, max_retries=1, backoff_seconds=0.5)
        self.source_url: Optional[str] = None

    def _load_competition(self) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        errors: List[str] = []
        for url in _competition_url_candidates(self.competition_id, self.season_id):
            try:
                soup = self.web_client.get_soup(url)
                name = _competition_name_from_soup(soup)
                clubs = _parse_competition_clubs(soup, self.season_id)
                if clubs:
                    self.source_url = url
                    return name, clubs
                errors.append(f"no clubs parsed from {url}")
            except Exception as exc:
                errors.append(_extract_error_message(exc))
                continue

        raise HTTPException(
            status_code=502,
            detail={
                "message": "Could not load competition clubs from Transfermarkt",
                "competition_id": self.competition_id,
                "season_id": self.season_id,
                "attempted_urls": _competition_url_candidates(self.competition_id, self.season_id),
                "errors": errors[-6:],
            },
        )

    def _load_single_club(self, club: Dict[str, Any], competition_name: Optional[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Optional[str]]:
        roster_url = club.get("roster_url")
        if not roster_url:
            return club, [], "missing roster_url"
        try:
            soup = self.web_client.get_soup(str(roster_url))
            players = _parse_club_players(soup, club, self.competition_id, competition_name, self.season_id)
            if not players:
                return club, [], f"no players parsed from {roster_url}"
            return club, players, None
        except Exception as exc:
            return club, [], _extract_error_message(exc)

    def _load_all_players(self, clubs: List[Dict[str, Any]], competition_name: Optional[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        club_summaries: List[Dict[str, Any]] = []
        all_players: List[Dict[str, Any]] = []
        errors: List[str] = []
        if not clubs:
            return club_summaries, all_players, errors

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(clubs))) as executor:
            futures = [executor.submit(self._load_single_club, club, competition_name) for club in clubs]
            for future in as_completed(futures):
                club, players, error = future.result()
                club_summaries.append(
                    {
                        "id": str(club.get("id")),
                        "name": club.get("name"),
                        "source_url": club.get("source_url"),
                        "roster_url": club.get("roster_url"),
                        "player_count": len(players),
                        "error": error,
                    }
                )
                all_players.extend(players)
                if error:
                    errors.append(f"club {club.get('id')} {club.get('name')}: {error}")

        club_summaries.sort(key=lambda item: item.get("name") or item.get("id") or "")
        all_players.sort(key=lambda item: ((item.get("club_name") or ""), (item.get("name") or "")))
        return club_summaries, all_players, errors

    def _performance_for_player(self, tm_id: str) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
        try:
            service = TransfermarktV2PlayerPerformance(tm_id=tm_id, client=self.performance_client)
            payload = service.get_performance()
            stats = payload.get("performance_stats", []) if isinstance(payload, dict) else []
            return tm_id, stats if isinstance(stats, list) else [], None
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
                    # Performance darf den Roster nie hart kaputt machen.
                    errors.append(f"performance {tm_id}: {error}")

        for player in players:
            tm_id = str(player.get("tm_id"))
            player["performance_stats"] = performance_by_tm_id.get(tm_id, [])
            player["performance_error"] = error_by_tm_id.get(tm_id)

        return errors

    def get_roster(self) -> Dict[str, Any]:
        if not self.competition_id:
            raise HTTPException(status_code=400, detail="competition_id is required")

        competition_name, clubs = self._load_competition()
        club_summaries, players, errors = self._load_all_players(clubs, competition_name)
        errors.extend(self._attach_performance(players))

        return {
            "competition_id": self.competition_id,
            "competition_name": competition_name,
            "season_id": self.season_id,
            "season_name": _season_name_from_id(self.season_id),
            "source_url": self.source_url,
            "loaded_at": datetime.now(),
            "include_performance": self.include_performance,
            "club_count": len(clubs),
            "player_count": len(players),
            "unique_player_count": len({player.get("tm_id") for player in players if player.get("tm_id")}),
            "clubs": club_summaries,
            "players": players,
            "errors": errors,
        }
