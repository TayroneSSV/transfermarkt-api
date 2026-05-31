from datetime import date
from typing import Optional, Union, Union

from app.schemas.base import AuditMixin, TransfermarktBaseModel


class PlayerTransferClub(TransfermarktBaseModel):
    id: str
    name: str


class PlayerTransfer(TransfermarktBaseModel):
    id: str
    club_from: PlayerTransferClub
    club_to: PlayerTransferClub
    date: date
    upcoming: bool
    season: str
    market_value: Optional[int]
    fee: Optional[Union[int, str]] = None
    transferFee: Optional[Union[int, str]] = None


class PlayerTransfers(TransfermarktBaseModel, AuditMixin):
    id: str
    transfers: list[PlayerTransfer]
    youth_clubs: Optional[list[str]]
