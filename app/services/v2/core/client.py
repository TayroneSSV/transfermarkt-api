from dataclasses import dataclass
from time import sleep
from typing import Optional

import requests
from fastapi import HTTPException
from requests import Response


@dataclass
class TransfermarktV2Client:
    timeout_seconds: int = 20
    max_retries: int = 3
    backoff_seconds: float = 1.0

    def get(self, url: str, params: Optional[dict] = None) -> Response:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
        }

        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = requests.get(url, params=params, headers=headers, timeout=self.timeout_seconds)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                    sleep(self.backoff_seconds * attempt)
                    continue
                if 400 <= response.status_code < 500:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Transfermarkt client error {response.status_code} for url: {response.url}",
                    )
                if 500 <= response.status_code < 600:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Transfermarkt server error {response.status_code} for url: {response.url}",
                    )
                return response
            except HTTPException:
                raise
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    sleep(self.backoff_seconds * attempt)
                    continue

        raise HTTPException(status_code=502, detail=f"Transfermarkt request failed for url: {url}. {last_error}")
