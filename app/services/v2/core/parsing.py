import re
from typing import Optional, Union
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

TRANSFERMARKT_BASE_URL = "https://www.transfermarkt.com"


def clean_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).replace("\xa0", " ").split())
    return text or None


def absolute_url(href: Optional[str]) -> Optional[str]:
    if not href:
        return None
    return urljoin(TRANSFERMARKT_BASE_URL, href)


def extract_id_from_url(url: Optional[str], marker: str) -> Optional[str]:
    if not url:
        return None
    match = re.search(rf"/{re.escape(marker)}/([^/?#]+)", url)
    return match.group(1) if match else None


def parse_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    text = value.replace(".", "").replace(",", "").replace("'", "")
    text = re.sub(r"[^0-9-]", "", text)
    if text in {"", "-"}:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def normalize_header(value: Optional[str]) -> str:
    text = clean_text(value) or ""
    text = text.lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
        "/": " ",
        "-": " ",
        ":": " ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return " ".join(text.split())


def get_link_by_url_part(cell: Tag, url_parts: tuple[str, ...]) -> tuple[Optional[str], Optional[str]]:
    for link in cell.find_all("a", href=True):
        href = link.get("href")
        if href and any(part in href for part in url_parts):
            label = clean_text(link.get("title")) or clean_text(link.get_text(" "))
            if not label:
                image = link.find("img")
                if image:
                    label = clean_text(image.get("title")) or clean_text(image.get("alt"))
            return absolute_url(href), label
    return None, None


def soup_from_html(html: Union[bytes, str]) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")
