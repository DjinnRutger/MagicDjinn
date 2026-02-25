"""
Scryfall API wrapper — pure HTTP layer, no database interaction.

All functions respect Scryfall's rate-limit guidance (max 10 req/s).
A 0.1 s sleep is applied between calls. Functions raise ScryfallError
on any non-200 response or network failure so callers can handle
gracefully without crashing an import job.

Scryfall API reference: https://scryfall.com/docs/api
"""
import time
import json
import logging
import requests

log = logging.getLogger(__name__)

_BASE = "https://api.scryfall.com"
_SESSION = requests.Session()
_SESSION.headers.update({"Accept": "application/json;q=0.9,*/*;q=0.8"})
_RATE_SLEEP = 0.1  # seconds between requests (Scryfall ToS)


class ScryfallError(Exception):
    """Raised when Scryfall returns an error or the network fails."""
    def __init__(self, message: str, status_code: int = None, not_found: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.not_found = not_found


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get(url: str, params: dict = None) -> dict:
    """Make a rate-limited GET request and return parsed JSON."""
    time.sleep(_RATE_SLEEP)
    try:
        resp = _SESSION.get(url, params=params, timeout=10)
    except requests.RequestException as exc:
        raise ScryfallError(f"Network error contacting Scryfall: {exc}") from exc

    if resp.status_code == 404:
        raise ScryfallError("Card not found", status_code=404, not_found=True)
    if resp.status_code == 429:
        raise ScryfallError("Scryfall rate limit hit — try again shortly", status_code=429)
    if not resp.ok:
        raise ScryfallError(
            f"Scryfall returned {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
        )

    return resp.json()


def _image_uris(data: dict) -> dict:
    """Extract image URIs, handling double-faced cards (image_uris lives in card_faces)."""
    uris = data.get("image_uris")
    if not uris and data.get("card_faces"):
        uris = data["card_faces"][0].get("image_uris", {})
    return uris or {}


def _oracle_text(data: dict) -> str:
    """Extract oracle text, combining both faces for DFCs."""
    text = data.get("oracle_text")
    if text is None and data.get("card_faces"):
        parts = [f.get("oracle_text", "") for f in data["card_faces"]]
        text = " // ".join(p for p in parts if p)
    return text or ""


def normalize_card(data: dict) -> dict:
    """
    Convert a raw Scryfall card object into a flat dict matching our Card model.
    Safe to call with any valid Scryfall card object (single-faced or DFC).
    """
    uris = _image_uris(data)
    prices = data.get("prices", {})
    colors = data.get("colors", [])
    color_identity = data.get("color_identity", [])
    legalities = data.get("legalities", {})

    return {
        "scryfall_id":      data["id"],
        "oracle_id":        data.get("oracle_id"),
        "name":             data["name"],
        "set_code":         data.get("set", "").upper(),
        "set_name":         data.get("set_name", ""),
        "collector_number": data.get("collector_number", ""),
        "image_normal":     uris.get("normal"),
        "image_small":      uris.get("small"),
        "image_art_crop":   uris.get("art_crop"),
        "usd":              float(prices["usd"])      if prices.get("usd")      else None,
        "usd_foil":         float(prices["usd_foil"]) if prices.get("usd_foil") else None,
        "mana_cost":        data.get("mana_cost", ""),
        "cmc":              float(data.get("cmc", 0)),
        "type_line":        data.get("type_line", ""),
        "oracle_text":      _oracle_text(data),
        "colors":           "".join(colors),
        "color_identity":   "".join(color_identity),
        "rarity":           data.get("rarity", ""),
        "power":            data.get("power"),
        "toughness":        data.get("toughness"),
        "loyalty":          data.get("loyalty"),
        "keywords":         json.dumps(data.get("keywords", [])),
        "legalities":       json.dumps(legalities),
        "frame_effects":    data.get("frame_effects", []),
        "finishes":         data.get("finishes", ["nonfoil"]),
    }


# ── Public API functions ──────────────────────────────────────────────────────

def get_card_by_name(name: str, fuzzy: bool = False) -> dict:
    """
    Fetch a card by name from Scryfall.

    Args:
        name:  Card name (exact or fuzzy).
        fuzzy: If True, use Scryfall's fuzzy match (tolerates typos).

    Returns:
        Normalized card dict (see normalize_card).

    Raises:
        ScryfallError: Card not found or API error.
    """
    params = {"fuzzy": name} if fuzzy else {"exact": name}
    data = _get(f"{_BASE}/cards/named", params=params)
    return normalize_card(data)


def get_card_by_id(scryfall_id: str) -> dict:
    """
    Fetch a specific card printing by its Scryfall UUID.

    Returns:
        Normalized card dict.

    Raises:
        ScryfallError: Not found or API error.
    """
    data = _get(f"{_BASE}/cards/{scryfall_id}")
    return normalize_card(data)


def get_card_by_set(set_code: str, collector_number: str) -> dict:
    """
    Fetch a specific printing by set code + collector number.
    This is the most precise lookup and avoids ambiguity.

    Returns:
        Normalized card dict.

    Raises:
        ScryfallError: Not found or API error.
    """
    data = _get(f"{_BASE}/cards/{set_code.lower()}/{collector_number}")
    return normalize_card(data)


def search_cards(query: str, page: int = 1) -> list[dict]:
    """
    Search Scryfall using a full Scryfall search query string.
    Returns up to 175 results per page (Scryfall default).

    Args:
        query: Scryfall query string, e.g. 'c:red t:creature cmc<=2'
        page:  Page number (1-indexed).

    Returns:
        List of normalized card dicts.

    Raises:
        ScryfallError: Bad query or API error.
    """
    data = _get(f"{_BASE}/cards/search", params={"q": query, "page": page})
    return [normalize_card(card) for card in data.get("data", [])]


def get_printings(oracle_id: str) -> list[dict]:
    """
    Return all printings of a card identified by its oracle_id.
    Useful for the "choose art" feature.

    Returns:
        List of normalized card dicts, sorted newest-first.

    Raises:
        ScryfallError: API error.
    """
    data = _get(
        f"{_BASE}/cards/search",
        params={
            "q":      f"oracleid:{oracle_id}",
            "unique": "prints",   # return every individual printing, not just one per card
            "order":  "released",
            "dir":    "desc",
        },
    )
    return [normalize_card(card) for card in data.get("data", [])]
