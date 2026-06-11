from dataclasses import dataclass
from typing import List, Optional

from fastapi import HTTPException

from app.services.base import TransfermarktBase
from app.utils.regex import REGEX_DOB
from app.utils.utils import extract_from_url, safe_regex
from app.utils.xpath import Clubs


def _club_roster_url_candidates(club_id: Optional[str], season_id: Optional[str]) -> List[str]:
    club_id = str(club_id or "").strip()
    season_id = str(season_id or "").strip() or None

    urls: List[str] = []
    if season_id:
        urls.append(f"https://www.transfermarkt.com/-/kader/verein/{club_id}/saison_id/{season_id}/plus/1")
        urls.append(f"https://www.transfermarkt.com/-/kader/verein/{club_id}/plus/1/galerie/0?saison_id={season_id}")
        urls.append(f"https://www.transfermarkt.com/-/kader/verein/{club_id}/saison_id/{season_id}")

    urls.append(f"https://www.transfermarkt.com/-/kader/verein/{club_id}/plus/1")
    urls.append(f"https://www.transfermarkt.com/-/kader/verein/{club_id}")

    deduped: List[str] = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped


@dataclass
class TransfermarktClubPlayers(TransfermarktBase):
    club_id: str = None
    season_id: str = None
    URL: str = "https://www.transfermarkt.com/-/kader/verein/{club_id}/saison_id/{season_id}/plus/1"

    def __post_init__(self) -> None:
        errors: List[str] = []
        for candidate_url in _club_roster_url_candidates(self.club_id, self.season_id):
            self.URL = candidate_url
            try:
                self.page = self.request_url_page()
                if self.get_text_by_xpath(Clubs.Players.CLUB_NAME):
                    self.__update_season_id()
                    self.__update_past_flag()
                    return
                errors.append(f"no club name at {candidate_url}")
            except HTTPException as exc:
                errors.append(str(exc.detail))
                continue

        raise HTTPException(
            status_code=502,
            detail={
                "message": "Could not load club roster from Transfermarkt",
                "club_id": self.club_id,
                "season_id": self.season_id,
                "attempted_urls": _club_roster_url_candidates(self.club_id, self.season_id),
                "errors": errors[-5:],
            },
        )

    def __update_season_id(self):
        if self.season_id is None:
            self.season_id = extract_from_url(self.get_text_by_xpath(Clubs.Players.CLUB_URL), "season_id")

    def __update_past_flag(self) -> None:
        self.past = "Current club" in self.get_list_by_xpath(Clubs.Players.PAST_FLAG)

    def __parse_club_players(self) -> list[dict]:
        page_nationalities = self.page.xpath(Clubs.Players.PAGE_NATIONALITIES)
        page_players_infos = self.page.xpath(Clubs.Players.PAGE_INFOS)
        page_players_signed_from = self.page.xpath(
            Clubs.Players.Past.PAGE_SIGNED_FROM if self.past else Clubs.Players.Present.PAGE_SIGNED_FROM,
        )
        page_players_joined_on = self.page.xpath(
            Clubs.Players.Past.PAGE_JOINED_ON if self.past else Clubs.Players.Present.PAGE_JOINED_ON,
        )
        players_ids = [extract_from_url(url) for url in self.get_list_by_xpath(Clubs.Players.URLS)]
        players_names = self.get_list_by_xpath(Clubs.Players.NAMES)
        players_positions = self.get_list_by_xpath(Clubs.Players.POSITIONS)
        players_dobs = [
            safe_regex(dob_age, REGEX_DOB, "dob") for dob_age in self.get_list_by_xpath(Clubs.Players.DOB_AGE)
        ]
        players_ages = [
            safe_regex(dob_age, REGEX_DOB, "age") for dob_age in self.get_list_by_xpath(Clubs.Players.DOB_AGE)
        ]
        players_nationalities = [nationality.xpath(Clubs.Players.NATIONALITIES) for nationality in page_nationalities]
        players_current_club = (
            self.get_list_by_xpath(Clubs.Players.Past.CURRENT_CLUB) if self.past else [None] * len(players_ids)
        )
        players_heights = self.get_list_by_xpath(
            Clubs.Players.Past.HEIGHTS if self.past else Clubs.Players.Present.HEIGHTS,
        )
        players_foots = self.get_list_by_xpath(
            Clubs.Players.Past.FOOTS if self.past else Clubs.Players.Present.FOOTS,
            remove_empty=False,
        )
        players_joined_on = ["; ".join(e.xpath(Clubs.Players.JOINED_ON)) for e in page_players_joined_on]
        players_joined = ["; ".join(e.xpath(Clubs.Players.JOINED)) for e in page_players_infos]
        players_signed_from = ["; ".join(e.xpath(Clubs.Players.SIGNED_FROM)) for e in page_players_signed_from]
        players_contracts = (
            [None] * len(players_ids) if self.past else self.get_list_by_xpath(Clubs.Players.Present.CONTRACTS)
        )
        players_marketvalues = self.get_list_by_xpath(Clubs.Players.MARKET_VALUES)
        players_statuses = ["; ".join(e.xpath(Clubs.Players.STATUSES)) for e in page_players_infos if e is not None]

        return [
            {
                "id": idx,
                "name": name,
                "position": position,
                "dateOfBirth": dob,
                "age": age,
                "nationality": nationality,
                "currentClub": current_club,
                "height": height,
                "foot": foot,
                "joinedOn": joined_on,
                "joined": joined,
                "signedFrom": signed_from,
                "contract": contract,
                "marketValue": market_value,
                "status": status,
            }
            for idx, name, position, dob, age, nationality, current_club, height, foot, joined_on, joined, signed_from, contract, market_value, status in zip(
                players_ids,
                players_names,
                players_positions,
                players_dobs,
                players_ages,
                players_nationalities,
                players_current_club,
                players_heights,
                players_foots,
                players_joined_on,
                players_joined,
                players_signed_from,
                players_contracts,
                players_marketvalues,
                players_statuses,
            )
        ]

    def get_club_players(self) -> dict:
        self.response["id"] = self.club_id
        self.response["source_url"] = self.URL
        self.response["players"] = self.__parse_club_players()
        return self.response
