"""
Tests for the decklist parser in app.utils.card_service.

These tests are pure unit tests — no database, no Scryfall API calls.
They cover parse_line() and parse_decklist() exhaustively so we can
catch regressions when adding new decklist formats.

Run with:  python -m pytest tests/ -v
"""
import pytest
from app.utils.card_service import parse_line, parse_decklist, ParsedLine


# ── parse_line ────────────────────────────────────────────────────────────────

class TestParseLine:

    # ── Basic formats ─────────────────────────────────────────────────────────

    def test_basic(self):
        r = parse_line("4 Lightning Bolt")
        assert r is not None
        assert r.quantity == 4
        assert r.name == "Lightning Bolt"
        assert r.set_code is None
        assert r.is_foil is False

    def test_x_suffix(self):
        r = parse_line("4x Lightning Bolt")
        assert r.quantity == 4
        assert r.name == "Lightning Bolt"

    def test_x_prefix(self):
        r = parse_line("x4 Lightning Bolt")
        assert r.quantity == 4
        assert r.name == "Lightning Bolt"

    def test_quantity_one(self):
        r = parse_line("1 Sol Ring")
        assert r.quantity == 1
        assert r.name == "Sol Ring"

    def test_multiword_name(self):
        r = parse_line("4 Arid Mesa")
        assert r.name == "Arid Mesa"

    def test_long_name(self):
        r = parse_line("1 Oko, Thief of Crowns")
        assert r.name == "Oko, Thief of Crowns"

    # ── Set code ─────────────────────────────────────────────────────────────

    def test_set_code(self):
        r = parse_line("4 Lightning Bolt (LEA)")
        assert r.name == "Lightning Bolt"
        assert r.set_code == "LEA"
        assert r.collector_number is None

    def test_set_code_lowercase(self):
        r = parse_line("4 Lightning Bolt (lea)")
        assert r.set_code == "LEA"

    def test_set_code_with_collector_number(self):
        r = parse_line("4 Lightning Bolt (LEA) 1")
        assert r.set_code == "LEA"
        assert r.collector_number == "1"

    def test_set_code_alphanumeric_collector(self):
        """Arena-style collector numbers like '357a'."""
        r = parse_line("1 Forest (2X2) 357")
        assert r.set_code == "2X2"
        assert r.collector_number == "357"

    def test_set_code_not_in_name(self):
        """The (SET) part must not end up in the card name."""
        r = parse_line("1 Black Lotus (LEA) 232")
        assert r.name == "Black Lotus"
        assert r.set_code == "LEA"

    # ── Foil detection ────────────────────────────────────────────────────────

    def test_foil_star(self):
        r = parse_line("4 Lightning Bolt *F*")
        assert r.is_foil is True
        assert r.name == "Lightning Bolt"

    def test_foil_star_lowercase(self):
        r = parse_line("4 Lightning Bolt *f*")
        assert r.is_foil is True

    def test_foil_parens(self):
        r = parse_line("4 Lightning Bolt (foil)")
        assert r.is_foil is True
        assert "foil" not in r.name.lower()

    def test_foil_with_set_code(self):
        r = parse_line("1 Black Lotus (LEA) *F*")
        assert r.is_foil is True
        assert r.set_code == "LEA"
        assert r.name == "Black Lotus"

    def test_not_foil(self):
        r = parse_line("4 Lightning Bolt")
        assert r.is_foil is False

    # ── Lines to skip ─────────────────────────────────────────────────────────

    def test_blank_line(self):
        assert parse_line("") is None
        assert parse_line("   ") is None

    def test_comment_double_slash(self):
        assert parse_line("// This is a comment") is None

    def test_comment_hash(self):
        assert parse_line("# This is a comment") is None

    def test_sideboard_prefix(self):
        assert parse_line("SB: 4 Lightning Bolt") is None

    def test_section_header(self):
        assert parse_line("Sideboard") is None

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_no_quantity(self):
        """Lines without a leading number should fail."""
        assert parse_line("Lightning Bolt") is None

    def test_quantity_zero(self):
        assert parse_line("0 Lightning Bolt") is None

    def test_quantity_too_high(self):
        assert parse_line("100 Lightning Bolt") is None

    def test_raw_preserved(self):
        raw = "4 Lightning Bolt (LEA) 1 *F*"
        r = parse_line(raw)
        assert r.raw == raw.strip()

    def test_extra_whitespace(self):
        r = parse_line("  4   Lightning Bolt  ")
        assert r is not None
        assert r.quantity == 4
        assert r.name == "Lightning Bolt"


# ── parse_decklist ────────────────────────────────────────────────────────────

class TestParseDecklist:

    def test_empty_string(self):
        parsed, failures = parse_decklist("")
        assert parsed == []
        assert failures == []

    def test_basic_list(self):
        text = """
4 Lightning Bolt
4 Goblin Guide
20 Mountain
"""
        parsed, failures = parse_decklist(text)
        assert len(parsed) == 3
        assert failures == []
        assert parsed[0].name == "Lightning Bolt"
        assert parsed[0].quantity == 4

    def test_mixed_valid_and_invalid(self):
        text = """
4 Lightning Bolt
this is not a card line
2 Sol Ring
"""
        parsed, failures = parse_decklist(text)
        assert len(parsed) == 2
        assert len(failures) == 1
        assert "not a card line" in failures[0]["line"]

    def test_comments_skipped(self):
        text = """
// Burn package
4 Lightning Bolt
# Land base
20 Mountain
"""
        parsed, failures = parse_decklist(text)
        assert len(parsed) == 2
        assert failures == []

    def test_blank_lines_skipped(self):
        text = "4 Lightning Bolt\n\n\n4 Goblin Guide\n"
        parsed, failures = parse_decklist(text)
        assert len(parsed) == 2

    def test_foil_in_list(self):
        text = "4 Lightning Bolt *F*\n4 Goblin Guide"
        parsed, _ = parse_decklist(text)
        assert parsed[0].is_foil is True
        assert parsed[1].is_foil is False

    def test_full_realistic_decklist(self):
        text = """
// Burn
4 Lightning Bolt (M11)
4x Rift Bolt
4 Lava Spike (CHK) 178

// Creatures
4 Goblin Guide (ZEN) 136
4 Monastery Swiftspear *F*

// Lands
20 Mountain
"""
        parsed, failures = parse_decklist(text)
        assert len(parsed) == 6  # 6 card lines; comments/blanks are excluded
        assert failures == []

        bolt = next(p for p in parsed if p.name == "Lightning Bolt")
        assert bolt.set_code == "M11"

        spike = next(p for p in parsed if p.name == "Lava Spike")
        assert spike.set_code == "CHK"
        assert spike.collector_number == "178"

        swift = next(p for p in parsed if p.name == "Monastery Swiftspear")
        assert swift.is_foil is True

    def test_quantities_sum(self):
        text = "4 Lightning Bolt\n4 Goblin Guide\n20 Mountain\n"
        parsed, _ = parse_decklist(text)
        total = sum(p.quantity for p in parsed)
        assert total == 28
