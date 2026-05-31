from dataclasses import dataclass
import re

from app.services.base import TransfermarktBase
from app.utils.utils import extract_from_url, safe_split
from app.utils.xpath import Players


@dataclass
class TransfermarktPlayerTransfers(TransfermarktBase):
    """
    A class for retrieving and parsing the player's transfer history and youth club details from Transfermarkt.

    Args:
        player_id (str): The unique identifier of the player.
        URL (str): The URL template for the player's transfers page on Transfermarkt.
    """

    player_id: str = None
    URL: str = "https://www.transfermarkt.com/-/transfers/spieler/{player_id}"
    URL_TRANSFERS: str = "https://www.transfermarkt.com/ceapi/transferHistory/list/{player_id}"

    def __post_init__(self) -> None:
        """Initialize the TransfermarktPlayerTransfers class."""
        self.URL = self.URL.format(player_id=self.player_id)
        self.page = self.request_url_page()
        self.raise_exception_if_not_found(xpath=Players.Profile.NAME)
        self.transfer_history = self.make_request(url=self.URL_TRANSFERS.format(player_id=self.player_id))


    @staticmethod
    def __clean_fee_value(value):
        """Normalize a fee value from Transfermarkt JSON/HTML without guessing."""
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return value

        text = str(value).strip()
        text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

        if not text or text in {"-", "–", "—"}:
            return None

        lower = text.lower()

        if lower in {"0", "0€", "0 €"}:
            return "free transfer"

        if (
            "free transfer" in lower
            or "ablösefrei" in lower
            or "abloesefrei" in lower
            or lower == "free"
        ):
            return "free transfer"

        return text

    def __build_html_fee_map(self) -> dict:
        """
        Transfermarkt's CE transferHistory endpoint often returns fee=null.
        The visible transfer page can still contain the fee text in the last table column.
        This method maps transfer_id -> fee text from the HTML page.
        """
        fee_map = {}

        rows = self.page.xpath(
            "//table[contains(@class, 'items')]//tbody//tr[.//a[contains(@href, 'transfer_id')]]"
        )

        for row in rows:
            hrefs = row.xpath(".//a[contains(@href, 'transfer_id')]/@href")
            transfer_id = None

            for href in hrefs:
                transfer_id = extract_from_url(href, "transfer_id")
                if transfer_id:
                    break

            if not transfer_id:
                continue

            cells = row.xpath("./td")
            if not cells:
                continue

            # In the transfer-history table, the fee is the last visible column.
            fee_text = " ".join(
                t.strip()
                for t in cells[-1].xpath(".//text()")
                if t and t.strip()
            ).strip()

            cleaned_fee = self.__clean_fee_value(fee_text)

            if cleaned_fee is not None:
                fee_map[transfer_id] = cleaned_fee

        return fee_map

    def __parse_player_transfer_history(self) -> list:
        """
        Parse and retrieve the transfer history of the specified player from Transfermarkt,
        including the unique identifier of each transfer, source club information (ID and name),
        destination club information (ID and name), transfer date, upcoming status, season, market
        value at the time of transfer, and transfer fee.

        Returns:
            list: A list of dictionaries, each containing details of the player's transfer history,
        """
        transfers = self.transfer_history.json().get("transfers") or []
        html_fee_map = self.__build_html_fee_map()

        parsed_transfers = []

        for transfer in transfers:
            transfer_id = extract_from_url(transfer.get("url"), "transfer_id")
            json_fee = transfer.get("fee")
            fee = self.__clean_fee_value(json_fee)

            if fee is None and isinstance(json_fee, str) and json_fee.strip():
                fee = json_fee.strip()

            if fee is None and transfer_id:
                fee = html_fee_map.get(transfer_id)

            parsed_transfers.append(
                {
                    "id": transfer_id,
                    "clubFrom": {
                        "id": extract_from_url(transfer["from"]["href"]),
                        "name": transfer["from"]["clubName"],
                    },
                    "clubTo": {
                        "id": extract_from_url(transfer["to"]["href"]),
                        "name": transfer["to"]["clubName"],
                    },
                    "date": transfer["date"],
                    "upcoming": transfer["upcoming"],
                    "season": transfer["season"],
                    "marketValue": transfer["marketValue"],
                    "fee": fee,
                    "transferFee": fee,
                }
            )

        return parsed_transfers

    def get_player_transfers(self) -> dict:
        """
        Retrieve and parse the transfer history and youth clubs of the specified player from Transfermarkt.

        Returns:
            dict: A dictionary containing the player's unique identifier, parsed transfer history, youth clubs,
                  and the timestamp of when the data was last updated.
        """
        self.response["id"] = self.player_id
        self.response["transfers"] = self.__parse_player_transfer_history()
        self.response["youthClubs"] = safe_split(self.get_text_by_xpath(Players.Transfers.YOUTH_CLUBS), ",")

        return self.response
