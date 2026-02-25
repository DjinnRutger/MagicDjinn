"""Moxfield deck import utility.

Fetches a public Moxfield deck by URL and returns a structured MoxfieldDeck
object ready for bulk import into a user's deck.

Only public decks are supported (no auth token required).

Note: Moxfield's API uses Cloudflare protection. We send browser-realistic
headers to avoid 403s. If it still fails (e.g. Cloudflare JS challenge),
the error message tells the user to export as text and paste instead.
"""
import re
import logging
import requests
from dataclasses import dataclass

log = logging.getLogger(__name__)

MOXFIELD_API = "https://api2.moxfield.com/v2/decks/all/{}"
DECK_ID_RE   = re.compile(r"moxfield\.com/decks/([A-Za-z0-9_-]+)")

_FALLBACK_MSG = (
    "Moxfield blocked the request (their API has bot protection). "
    "Please export your deck from Moxfield as a text file "
    "(Moxfield → Export → Text) and paste it using the "
    "\u201cPaste decklist\u201d option instead."
)

# Browser-realistic headers that satisfy Moxfield's Cloudflare check
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.moxfield.com/",
    "Origin":          "https://www.moxfield.com",
    "sec-ch-ua":       '"Chromium";v="124","Google Chrome";v="124","Not-A.Brand";v="99"',
    "sec-ch-ua-mobile":   "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest":  "empty",
    "Sec-Fetch-Mode":  "cors",
    "Sec-Fetch-Site":  "same-site",
    "Connection":      "keep-alive",
}


@dataclass
class MoxfieldCard:
    name: str
    quantity: int
    is_foil: bool
    is_sideboard: bool
    scryfall_id: str | None
    set_code: str | None


@dataclass
class MoxfieldDeck:
    name: str
    format: str
    cards: list  # list[MoxfieldCard]
    error: str | None = None


def fetch_moxfield_deck(url: str) -> MoxfieldDeck:
    """Fetch a public Moxfield deck by URL.

    Returns a MoxfieldDeck with error set if anything goes wrong.
    Never raises — all errors are captured in MoxfieldDeck.error.
    """
    m = DECK_ID_RE.search(url)
    if not m:
        return MoxfieldDeck("", "", [],
                            error="Invalid Moxfield URL — expected moxfield.com/decks/<id>")

    deck_id = m.group(1)
    api_url = MOXFIELD_API.format(deck_id)
    log.debug("Fetching Moxfield deck: %s", api_url)

    try:
        resp = requests.get(api_url, timeout=12, headers=_HEADERS)
    except requests.RequestException as e:
        return MoxfieldDeck("", "", [], error=f"Network error reaching Moxfield: {e}")

    if resp.status_code == 403:
        return MoxfieldDeck("", "", [], error=_FALLBACK_MSG)
    if resp.status_code == 404:
        return MoxfieldDeck("", "", [],
                            error="Deck not found on Moxfield — make sure the deck is set to Public.")
    if not resp.ok:
        return MoxfieldDeck("", "", [],
                            error=f"Moxfield returned HTTP {resp.status_code}. "
                                  "Try the decklist paste option instead.")

    try:
        data = resp.json()
    except Exception as e:
        return MoxfieldDeck("", "", [], error=f"Could not parse Moxfield response: {e}")

    cards: list[MoxfieldCard] = []
    _parse_section(data.get("mainboard", {}).get("cards", {}), cards, sideboard=False)
    _parse_section(data.get("sideboard",  {}).get("cards", {}), cards, sideboard=True)
    _parse_section(data.get("commanders", {}).get("cards", {}), cards, sideboard=False)
    _parse_section(data.get("companions", {}).get("cards", {}), cards, sideboard=False)

    fmt  = (data.get("format") or "Casual").capitalize()
    name = data.get("name") or "Imported Deck"

    log.info("Moxfield import: '%s' (%s) — %d cards", name, fmt, len(cards))
    return MoxfieldDeck(name=name, format=fmt, cards=cards)


def _parse_section(cards_dict: dict, out: list, sideboard: bool) -> None:
    """Parse one section of a Moxfield deck response into MoxfieldCard objects."""
    for entry in cards_dict.values():
        card = entry.get("card", {})
        scryfall_id = card.get("scryfall_id") or card.get("id") or None
        out.append(MoxfieldCard(
            name=card.get("name", ""),
            quantity=entry.get("quantity", 1),
            is_foil=bool(entry.get("isFoil", False)),
            is_sideboard=sideboard,
            scryfall_id=scryfall_id,
            set_code=card.get("set") or card.get("set_code") or None,
        ))
