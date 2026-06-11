from dataclasses import dataclass
from typing import List, Optional

from fastapi import HTTPException

from app.services.base import TransfermarktBase
from app.utils.utils import extract_from_url
from app.utils.xpath import Competitions


def _competition_url_candidates(competition_id: Optional[str], season_id: Optional[str]) -> List[str]:
    competition_id = str(competition_id or "").strip()
    season_id = str(season_id or "").strip() or None

    urls: List[str] = []
    if season_id:
        # Der alte Query-Parameter-Weg (/plus/?saison_id=...) liefert auf Render häufig 405.
        # Der Pfad-Weg ist robuster und wird zuerst probiert.
        urls.append(f"https://www.transfermarkt.com/-/startseite/wettbewerb/{competition_id}/saison_id/{season_id}")
        urls.append(f"https://www.transfermarkt.com/-/startseite/wettbewerb/{competition_id}/plus?saison_id={season_id}")
        urls.append(f"https://www.transfermarkt.com/-/startseite/wettbewerb/{competition_id}/plus/?saison_id={season_id}")

    urls.append(f"https://www.transfermarkt.com/-/startseite/wettbewerb/{competition_id}")
    urls.append(f"https://www.transfermarkt.com/-/startseite/wettbewerb/{competition_id}/plus")

    deduped: List[str] = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped


@dataclass
class TransfermarktCompetitionClubs(TransfermarktBase):
    competition_id: str = None
    season_id: str = None
    URL: str = "https://www.transfermarkt.com/-/startseite/wettbewerb/{competition_id}/saison_id/{season_id}"

    def __post_init__(self) -> None:
        errors: List[str] = []
        for candidate_url in _competition_url_candidates(self.competition_id, self.season_id):
            self.URL = candidate_url
            try:
                self.page = self.request_url_page()
                if self.get_text_by_xpath(Competitions.Profile.NAME):
                    return
                errors.append(f"no competition name at {candidate_url}")
            except HTTPException as exc:
                errors.append(str(exc.detail))
                continue

        raise HTTPException(
            status_code=502,
            detail={
                "message": "Could not load competition clubs from Transfermarkt",
                "competition_id": self.competition_id,
                "season_id": self.season_id,
                "attempted_urls": _competition_url_candidates(self.competition_id, self.season_id),
                "errors": errors[-5:],
            },
        )

    def __parse_competition_clubs(self) -> list:
        urls = self.get_list_by_xpath(Competitions.Clubs.URLS)
        names = self.get_list_by_xpath(Competitions.Clubs.NAMES)
        ids = [extract_from_url(url) for url in urls]

        clubs = []
        seen = set()
        for idx, name in zip(ids, names):
            if not idx or idx in seen:
                continue
            seen.add(idx)
            clubs.append({"id": idx, "name": name})
        return clubs

    def get_competition_clubs(self) -> dict:
        self.response["id"] = self.competition_id
        self.response["name"] = self.get_text_by_xpath(Competitions.Profile.NAME)
        self.response["seasonId"] = extract_from_url(
            self.get_text_by_xpath(Competitions.Profile.URL),
            "season_id",
        ) or self.season_id
        self.response["source_url"] = self.URL
        self.response["clubs"] = self.__parse_competition_clubs()
        return self.response
