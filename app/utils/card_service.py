"""
Card service layer — bridges Scryfall API with the database.

This module owns all logic for:
  - Fetching cards from Scryfall and caching them in the Card table
  - Parsing raw decklist text into structured import jobs
  - Creating / updating Inventory rows for a user's Box

Callers (blueprints) never touch the Scryfall API directly; they go
through this module so caching, error handling, and rate-limiting are
always applied consistently.
"""
import json as _json
import re
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field

from app.extensions import db
from app.models.card import Card
from app.models.inventory import Inventory, CardCondition
from app.utils.scryfall import (
    ScryfallError,
    get_card_by_name,
    get_card_by_id,
    get_card_by_set,
)

log = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ParsedLine:
    """Result of parsing one line from a decklist."""
    quantity: int
    name: str
    set_code: str | None = None
    collector_number: str | None = None
    is_foil: bool = False
    is_sideboard: bool = False
    raw: str = ""


@dataclass
class ImportResult:
    """Summary of a bulk import operation."""
    successes: list = field(default_factory=list)
    failures:  list = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return sum(s["quantity"] for s in self.successes)

    @property
    def failure_count(self) -> int:
        return len(self.failures)


# ── Decklist parser ───────────────────────────────────────────────────────────

# Matches the optional (SET) and/or collector number that can follow a card name.
# Examples: (LEA), (LEA) 1, (2X2) 357, (PLST) BBD-190
# Collector numbers can be: plain digits "148", digit+letter "307b",
# or alpha-prefix+hyphen+digits "BBD-190" (used by The List reprints).
_SET_RE = re.compile(r"\(([A-Za-z0-9]{2,6})\)(?:\s+([A-Za-z0-9][A-Za-z0-9-]*))?", re.IGNORECASE)

# Foil indicators found in the wild
_FOIL_PATTERNS = re.compile(
    r"\*[Ff]\*"          # *F* or *f*
    r"|\(foil\)"         # (foil)
    r"|\[foil\]"         # [foil]
    r"|<foil>"           # <foil>
    r"|\+foil"           # +foil
    r"|\bfoil\b",        # standalone word
    re.IGNORECASE,
)

# Lines to skip entirely (section headers and comment markers)
# "Deck" is the opening header in Moxfield text exports.
_SKIP_RE = re.compile(r"^\s*(//|#|--|SB:|Sideboard|Commander|Companion|Deck).*$", re.IGNORECASE)

# Moxfield section markers that change the is_sideboard flag
_SECTION_RE = re.compile(r"^\s*(Deck|Commander|Companion|Sideboard)\s*$", re.IGNORECASE)

# Quantity at the start: "4 ", "4x ", "x4 "
_QTY_RE = re.compile(r"^[xX]?(\d+)[xX]?\s+")


def parse_line(raw: str) -> ParsedLine | None:
    """
    Parse one line of a decklist into a ParsedLine.

    Returns None for blank lines, comment lines, or unparseable input.
    Never raises — all errors are returned as None so the caller can
    accumulate failures without aborting the whole import.

    Supported formats:
      4 Lightning Bolt
      4x Lightning Bolt
      x4 Lightning Bolt
      4 Lightning Bolt (LEA)
      4 Lightning Bolt (LEA) 1
      4 Lightning Bolt *F*
      4 Lightning Bolt (foil)
      4 Lightning Bolt (2X2) 357 *F*
    """
    line = raw.strip()
    if not line:
        return None
    if _SKIP_RE.match(line):
        return None

    # Detect and strip foil indicators before parsing name
    is_foil = bool(_FOIL_PATTERNS.search(line))
    line = _FOIL_PATTERNS.sub("", line).strip()

    # Extract leading quantity
    qty_match = _QTY_RE.match(line)
    if not qty_match:
        return None
    quantity = int(qty_match.group(1))
    if quantity < 1 or quantity > 99:
        return None
    rest = line[qty_match.end():]

    # Extract set code + collector number if present
    set_code = None
    collector_number = None
    set_match = _SET_RE.search(rest)
    if set_match:
        set_code = set_match.group(1).upper()
        collector_number = set_match.group(2)  # may be None
        # Remove the (SET) block from the name
        rest = rest[:set_match.start()].strip()

    name = rest.strip().strip('"\'')
    if not name:
        return None

    return ParsedLine(
        quantity=quantity,
        name=name,
        set_code=set_code,
        collector_number=collector_number,
        is_foil=is_foil,
        raw=raw.strip(),
    )


def parse_decklist(text: str) -> tuple[list[ParsedLine], list[dict]]:
    """
    Parse a full decklist string.

    Returns:
        (parsed_lines, failures)
        parsed_lines: list of ParsedLine for lines that parsed OK
        failures:     list of {"line": str, "reason": str} for bad lines
    """
    parsed = []
    failures = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or _SKIP_RE.match(raw_line):
            continue
        result = parse_line(raw_line)
        if result is None:
            failures.append({
                "line": raw_line.strip(),
                "reason": "Could not parse line — expected format: '4 Card Name (SET)'",
            })
        else:
            parsed.append(result)
    return parsed, failures


# ── Card cache ────────────────────────────────────────────────────────────────

def get_or_create_card(
    name: str | None = None,
    scryfall_id: str | None = None,
    set_code: str | None = None,
    collector_number: str | None = None,
    fuzzy: bool = False,
    force_refresh: bool = False,
) -> Card:
    """
    Return a Card from the local cache, fetching from Scryfall if needed.

    Lookup priority:
      1. scryfall_id       (most precise)
      2. set_code + collector_number  (exact printing)
      3. name              (may return a default printing)

    Cache behaviour:
      - If the card exists in DB and is not stale, return it immediately.
      - If stale or missing, fetch from Scryfall and upsert.

    Args:
        name:             Card name for name-based lookup.
        scryfall_id:      Specific printing UUID.
        set_code:         Set abbreviation, e.g. "LEA".
        collector_number: Collector number within the set.
        fuzzy:            Allow fuzzy name matching (tolerates typos).
        force_refresh:    Bypass stale check and always re-fetch.

    Returns:
        Card model instance (possibly updated).

    Raises:
        ScryfallError: Card not found or network failure.
        ValueError:    No identifier provided.
    """
    if not any([scryfall_id, name, (set_code and collector_number)]):
        raise ValueError("Provide at least one of: scryfall_id, name, set_code+collector_number")

    # ── Try to find an existing cached card ───────────────────────────────────
    card: Card | None = None

    if scryfall_id:
        card = Card.query.get(scryfall_id)
    elif set_code and collector_number:
        card = Card.query.filter_by(
            set_code=set_code.upper(), collector_number=collector_number
        ).first()
    elif name:
        card = Card.query.filter(Card.name.ilike(name)).first()

    # Return cached card if fresh enough
    if card and not card.is_stale and not force_refresh:
        return card

    # ── Fetch from Scryfall ───────────────────────────────────────────────────
    if scryfall_id:
        card_data = get_card_by_id(scryfall_id)
    elif set_code and collector_number:
        card_data = get_card_by_set(set_code, collector_number)
    else:
        card_data = get_card_by_name(name, fuzzy=fuzzy)

    # ── Upsert into the cache ─────────────────────────────────────────────────
    sid = card_data["scryfall_id"]
    card = Card.query.get(sid)
    if card is None:
        card = Card(scryfall_id=sid)
        db.session.add(card)

    for attr, value in card_data.items():
        if attr != "scryfall_id":
            setattr(card, attr, value)
    card.last_updated = datetime.now(timezone.utc)
    db.session.flush()

    return card


# ── Bulk import ───────────────────────────────────────────────────────────────

def bulk_import_decklist(text: str, user_id: int, physical_location: str = "") -> ImportResult:
    """
    Parse a decklist string and add all cards to the user's Box.

    Cards that already exist in the user's Box (same scryfall_id + foil flag)
    have their quantity incremented rather than creating a duplicate row.

    Rate-limiting is handled inside get_or_create_card → scryfall.py.

    Args:
        text:    Raw decklist text pasted by the user.
        user_id: ID of the user whose Box receives the cards.

    Returns:
        ImportResult with successes and failures lists.
    """
    result = ImportResult()
    parsed_lines, parse_failures = parse_decklist(text)

    # Carry forward parse failures immediately
    result.failures.extend(parse_failures)

    for pl in parsed_lines:
        try:
            card = get_or_create_card(
                name=pl.name,
                set_code=pl.set_code,
                collector_number=pl.collector_number,
                fuzzy=False,
            )
        except ScryfallError as exc:
            # Try fuzzy match as fallback when exact name fails
            if exc.not_found:
                try:
                    card = get_or_create_card(name=pl.name, fuzzy=True)
                except ScryfallError:
                    result.failures.append({
                        "line": pl.raw,
                        "reason": f"Card not found: '{pl.name}'",
                    })
                    continue
            else:
                result.failures.append({
                    "line": pl.raw,
                    "reason": f"Scryfall error: {exc}",
                })
                continue

        # Find existing Box row for this card+foil combo or create new
        existing = Inventory.query.filter_by(
            user_id=user_id,
            card_scryfall_id=card.scryfall_id,
            is_foil=pl.is_foil,
            current_deck_id=None,  # Box only
        ).first()

        loc = physical_location.strip() if physical_location else None
        if existing:
            existing.quantity += pl.quantity
            # Only write location onto existing row if it had none
            if loc and not existing.physical_location:
                existing.physical_location = loc
            added = False
        else:
            existing = Inventory(
                user_id=user_id,
                card_scryfall_id=card.scryfall_id,
                quantity=pl.quantity,
                is_foil=pl.is_foil,
                condition=CardCondition.NM,
                physical_location=loc,
            )
            db.session.add(existing)
            added = True

        result.successes.append({
            "card":     card,
            "quantity": pl.quantity,
            "is_foil":  pl.is_foil,
            "added":    added,
        })

    db.session.commit()
    log.info(
        "Import complete for user %s: %d cards added, %d failures",
        user_id, result.success_count, result.failure_count,
    )
    return result


# ── Moxfield text-export parser ──────────────────────────────────────────────

def parse_moxfield_text(text: str) -> tuple[list[ParsedLine], list[dict]]:
    """Parse a Moxfield text export, correctly tagging sideboard cards.

    Moxfield exports look like:

        Deck
        1 Hearthhull, the Worldseed (EOC) 1
        1 Beast Within (PLST) BBD-190

        Sideboard
        1 Lightning Bolt (M11) 149

    Section headers (Deck / Commander / Companion / Sideboard) switch the
    is_sideboard flag.  Cards under "Sideboard" are tagged is_sideboard=True;
    all others are False.

    Returns the same (parsed_lines, failures) tuple as parse_decklist.
    """
    parsed: list[ParsedLine] = []
    failures: list[dict] = []
    in_sideboard = False

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue

        # Section header — update sideboard state, don't try to parse as a card
        sec = _SECTION_RE.match(stripped)
        if sec:
            in_sideboard = sec.group(1).lower() == "sideboard"
            continue

        # Skip comment/separator lines
        if _SKIP_RE.match(stripped):
            continue

        result = parse_line(raw_line)
        if result is None:
            failures.append({
                "line": stripped,
                "reason": "Could not parse line — expected: qty name (SET) collector#",
            })
        else:
            result.is_sideboard = in_sideboard
            parsed.append(result)

    return parsed, failures


# ── Deck-targeted import ──────────────────────────────────────────────────────

def bulk_import_to_deck(text: str, user_id: int, deck_id: int) -> ImportResult:
    """Parse a decklist string and add all cards directly to a specific deck.

    Cards do NOT go through the Box — they are added straight to the deck.
    Duplicate rows (same card + foil + sideboard flag) are merged by qty.

    Args:
        text:    Raw decklist text pasted by the user.
        user_id: ID of the owning user.
        deck_id: Target deck ID.

    Returns:
        ImportResult with successes and failures lists.
    """
    result = ImportResult()
    parsed_lines, parse_failures = parse_decklist(text)
    result.failures.extend(parse_failures)

    for pl in parsed_lines:
        try:
            card = get_or_create_card(
                name=pl.name,
                set_code=pl.set_code,
                collector_number=pl.collector_number,
                fuzzy=False,
            )
        except ScryfallError as exc:
            if exc.not_found:
                try:
                    card = get_or_create_card(name=pl.name, fuzzy=True)
                except ScryfallError:
                    result.failures.append({
                        "line": pl.raw,
                        "reason": f"Card not found: '{pl.name}'",
                    })
                    continue
            else:
                result.failures.append({
                    "line": pl.raw,
                    "reason": f"Scryfall error: {exc}",
                })
                continue

        try:
            _upsert_deck_row(user_id, deck_id, card.scryfall_id,
                             pl.quantity, pl.is_foil, is_sideboard=False)
            result.successes.append({"card": card, "quantity": pl.quantity})
        except Exception as exc:
            result.failures.append({"line": pl.raw, "reason": str(exc)})

    db.session.commit()
    return result


def bulk_import_moxfield_text(text: str, user_id: int, deck_id: int) -> ImportResult:
    """Parse a pasted Moxfield text export and add cards directly to a deck.

    Handles the Moxfield section format (Deck / Sideboard headers) so that
    sideboard cards are correctly tagged with is_sideboard=True.

    Args:
        text:    Raw text pasted from Moxfield's Export → Text.
        user_id: ID of the owning user.
        deck_id: Target deck ID.

    Returns:
        ImportResult with successes and failures lists.
    """
    result = ImportResult()
    parsed_lines, parse_failures = parse_moxfield_text(text)
    result.failures.extend(parse_failures)

    for pl in parsed_lines:
        try:
            card = get_or_create_card(
                name=pl.name,
                set_code=pl.set_code,
                collector_number=pl.collector_number,
                fuzzy=False,
            )
        except ScryfallError as exc:
            if exc.not_found:
                try:
                    card = get_or_create_card(name=pl.name, fuzzy=True)
                except ScryfallError:
                    result.failures.append({
                        "line": pl.raw,
                        "reason": f"Card not found: '{pl.name}'",
                    })
                    continue
            else:
                result.failures.append({
                    "line": pl.raw,
                    "reason": f"Scryfall error: {exc}",
                })
                continue

        try:
            _upsert_deck_row(user_id, deck_id, card.scryfall_id,
                             pl.quantity, pl.is_foil, pl.is_sideboard)
            result.successes.append({"card": card, "quantity": pl.quantity,
                                     "is_sideboard": pl.is_sideboard})
        except Exception as exc:
            result.failures.append({"line": pl.raw, "reason": str(exc)})

    db.session.commit()
    log.info(
        "Moxfield text import to deck %s for user %s: %d cards, %d failures",
        deck_id, user_id, result.success_count, result.failure_count,
    )
    return result


def import_moxfield_to_deck(mox_deck, user_id: int, deck_id: int) -> ImportResult:
    """Import a parsed MoxfieldDeck into a specific deck.

    Args:
        mox_deck: MoxfieldDeck dataclass (from moxfield.fetch_moxfield_deck).
        user_id:  ID of the owning user.
        deck_id:  Target deck ID.

    Returns:
        ImportResult with successes and failures lists.
    """
    result = ImportResult()

    for mc in mox_deck.cards:
        if not mc.name:
            continue
        try:
            card = get_or_create_card(
                name=mc.name,
                scryfall_id=mc.scryfall_id,
                set_code=mc.set_code,
            )
            _upsert_deck_row(user_id, deck_id, card.scryfall_id,
                             mc.quantity, mc.is_foil, mc.is_sideboard)
            result.successes.append({"card": card, "quantity": mc.quantity})
        except Exception as exc:
            result.failures.append({"line": mc.name, "reason": str(exc)})

    db.session.commit()
    log.info(
        "Moxfield import to deck %s for user %s: %d cards, %d failures",
        deck_id, user_id, result.success_count, result.failure_count,
    )
    return result


def _upsert_deck_row(
    user_id: int,
    deck_id: int,
    scryfall_id: str,
    qty: int,
    is_foil: bool,
    is_sideboard: bool,
) -> None:
    """Merge qty into an existing deck Inventory row, or create a new one."""
    existing = Inventory.query.filter_by(
        user_id=user_id,
        card_scryfall_id=scryfall_id,
        is_foil=is_foil,
        current_deck_id=deck_id,
        is_sideboard=is_sideboard,
    ).first()

    if existing:
        existing.quantity += qty
    else:
        db.session.add(Inventory(
            user_id=user_id,
            card_scryfall_id=scryfall_id,
            quantity=qty,
            is_foil=is_foil,
            current_deck_id=deck_id,
            is_sideboard=is_sideboard,
        ))


# ── Streaming import generators ───────────────────────────────────────────────

def stream_box_import(text: str, user_id: int, physical_location: str = ""):
    """Generator: yield NDJSON progress events while importing a decklist to the Box.

    Event sequence:
      {"type": "start",    "total": N}
      {"type": "progress", "current": i, "total": N, "card": name, "ok": bool}
      {"type": "done",     "successes": N, "failures": N, "failure_details": [...]}
    """
    parsed_lines, parse_failures = parse_decklist(text)
    total = len(parsed_lines)
    yield _json.dumps({"type": "start", "total": total}) + "\n"

    result = ImportResult()
    result.failures.extend(parse_failures)

    for i, pl in enumerate(parsed_lines):
        card_name = pl.name
        try:
            card = get_or_create_card(
                name=pl.name,
                set_code=pl.set_code,
                collector_number=pl.collector_number,
                fuzzy=False,
            )
        except ScryfallError as exc:
            if exc.not_found:
                try:
                    card = get_or_create_card(name=pl.name, fuzzy=True)
                except ScryfallError:
                    result.failures.append({"line": pl.raw, "reason": f"Card not found: '{pl.name}'"})
                    yield _json.dumps({"type": "progress", "current": i + 1, "total": total,
                                       "card": card_name, "ok": False}) + "\n"
                    continue
            else:
                result.failures.append({"line": pl.raw, "reason": f"Scryfall error: {exc}"})
                yield _json.dumps({"type": "progress", "current": i + 1, "total": total,
                                   "card": card_name, "ok": False}) + "\n"
                continue

        loc = physical_location.strip() if physical_location else None
        existing = Inventory.query.filter_by(
            user_id=user_id,
            card_scryfall_id=card.scryfall_id,
            is_foil=pl.is_foil,
            current_deck_id=None,
        ).first()
        if existing:
            existing.quantity += pl.quantity
            if loc and not existing.physical_location:
                existing.physical_location = loc
            added = False
        else:
            existing = Inventory(
                user_id=user_id,
                card_scryfall_id=card.scryfall_id,
                quantity=pl.quantity,
                is_foil=pl.is_foil,
                condition=CardCondition.NM,
                physical_location=loc,
            )
            db.session.add(existing)
            added = True

        db.session.flush()
        result.successes.append({
            "card": card, "quantity": pl.quantity, "is_foil": pl.is_foil, "added": added,
        })
        yield _json.dumps({"type": "progress", "current": i + 1, "total": total,
                           "card": card.name, "ok": True}) + "\n"

    db.session.commit()
    log.info("Stream box import user=%s: %d added, %d failures",
             user_id, result.success_count, result.failure_count)
    yield _json.dumps({
        "type": "done",
        "successes": result.success_count,
        "failures": result.failure_count,
        "failure_details": result.failures,
    }) + "\n"
    return result


def stream_deck_import(text: str, user_id: int, deck_id: int, moxfield: bool = False):
    """Generator: yield NDJSON progress events while importing a decklist to a deck.

    Event sequence:
      {"type": "start",    "total": N}
      {"type": "progress", "current": i, "total": N, "card": name, "ok": bool}

    Returns an ImportResult via StopIteration value, accessible with:
        result = yield from stream_deck_import(...)
    The caller is responsible for committing and yielding the "done" event.
    """
    if moxfield:
        parsed_lines, parse_failures = parse_moxfield_text(text)
    else:
        parsed_lines, parse_failures = parse_decklist(text)

    total = len(parsed_lines)
    yield _json.dumps({"type": "start", "total": total}) + "\n"

    result = ImportResult()
    result.failures.extend(parse_failures)

    for i, pl in enumerate(parsed_lines):
        card_name = pl.name
        try:
            card = get_or_create_card(
                name=pl.name,
                set_code=pl.set_code,
                collector_number=pl.collector_number,
                fuzzy=False,
            )
        except ScryfallError as exc:
            if exc.not_found:
                try:
                    card = get_or_create_card(name=pl.name, fuzzy=True)
                except ScryfallError:
                    result.failures.append({"line": pl.raw, "reason": f"Card not found: '{pl.name}'"})
                    yield _json.dumps({"type": "progress", "current": i + 1, "total": total,
                                       "card": card_name, "ok": False}) + "\n"
                    continue
            else:
                result.failures.append({"line": pl.raw, "reason": f"Scryfall error: {exc}"})
                yield _json.dumps({"type": "progress", "current": i + 1, "total": total,
                                   "card": card_name, "ok": False}) + "\n"
                continue

        try:
            _upsert_deck_row(
                user_id, deck_id, card.scryfall_id,
                pl.quantity, pl.is_foil,
                pl.is_sideboard if moxfield else False,
            )
            db.session.flush()
            result.successes.append({"card": card, "quantity": pl.quantity})
            yield _json.dumps({"type": "progress", "current": i + 1, "total": total,
                               "card": card.name, "ok": True}) + "\n"
        except Exception as exc:
            result.failures.append({"line": pl.raw, "reason": str(exc)})
            yield _json.dumps({"type": "progress", "current": i + 1, "total": total,
                               "card": card_name, "ok": False}) + "\n"

    db.session.commit()
    log.info("Stream deck import deck=%s user=%s: %d added, %d failures",
             deck_id, user_id, result.success_count, result.failure_count)
    return result
