from flask_wtf import FlaskForm
from wtforms import (
    StringField, TextAreaField, SelectField, BooleanField,
    RadioField, SubmitField,
)
from wtforms.validators import DataRequired, Length, Optional
from app.models.deck import MTG_FORMATS


class DeckForm(FlaskForm):
    name = StringField(
        "Deck Name",
        validators=[DataRequired(), Length(1, 100)],
        render_kw={"placeholder": "e.g. Jeskai Control, Jund Midrange…"},
    )
    description = TextAreaField(
        "Description",
        validators=[Optional(), Length(0, 1000)],
        render_kw={"rows": 3, "placeholder": "Optional notes about this deck…"},
    )
    format = SelectField(
        "Format",
        choices=[(f, f) for f in MTG_FORMATS],
        default="Casual",
    )
    is_visible_to_friends = BooleanField(
        "Visible to friends",
        description="Friends in your groups can view this deck (read-only).",
        default=True,
    )
    bracket = SelectField(
        "Bracket",
        choices=[
            ("", "— Not set —"),
            ("1", "Bracket 1 — Precon / Jank"),
            ("2", "Bracket 2 — Upgraded Precon"),
            ("3", "Bracket 3 — Optimized"),
            ("4", "Bracket 4 — High-Power"),
            ("5", "Bracket 5 — CEDH"),
        ],
        default="",
        validators=[Optional()],
    )

    # ── Import options (only shown on new deck) ───────────────────────────────
    import_type = RadioField(
        "Import cards from",
        choices=[
            ("empty",    "Start empty"),
            ("decklist", "Paste decklist"),
            ("moxfield", "Moxfield export (paste)"),
        ],
        default="empty",
    )
    decklist_text = TextAreaField(
        "Decklist",
        validators=[Optional()],
        render_kw={
            "rows": 10,
            "placeholder": (
                "4 Lightning Bolt (LEA)\n"
                "4 Counterspell\n"
                "1 Black Lotus (LEA) 232\n"
                "// One card per line: qty name (SET) collector#"
            ),
        },
    )
    moxfield_text = TextAreaField(
        "Moxfield export",
        validators=[Optional()],
        render_kw={
            "rows": 12,
            "placeholder": (
                "Paste the text from Moxfield → Export → Text\n\n"
                "Deck\n"
                "1 Hearthhull, the Worldseed (EOC) 1\n"
                "1 Beast Within (PLST) BBD-190\n\n"
                "Sideboard\n"
                "1 Lightning Bolt (M11) 149"
            ),
        },
    )
    mark_all_proxy = BooleanField(
        "Mark all imported cards as Proxy",
        default=False,
    )

    submit = SubmitField("Save Deck")


class DeckImportForm(FlaskForm):
    """Minimal form for streaming import of more cards into an existing deck."""
    import_type = RadioField(
        "Import from",
        choices=[
            ("decklist", "Paste decklist"),
            ("moxfield", "Moxfield export (paste)"),
        ],
        default="decklist",
    )
    decklist_text = TextAreaField(
        "Decklist",
        validators=[Optional()],
        render_kw={
            "rows": 10,
            "placeholder": (
                "4 Lightning Bolt (LEA)\n"
                "4 Counterspell\n"
                "1 Black Lotus (LEA) 232\n"
                "// One card per line: qty name (SET) collector#"
            ),
        },
    )
    moxfield_text = TextAreaField(
        "Moxfield export",
        validators=[Optional()],
        render_kw={
            "rows": 12,
            "placeholder": (
                "Paste the text from Moxfield → Export → Text\n\n"
                "Deck\n"
                "1 Hearthhull, the Worldseed (EOC) 1\n"
                "1 Beast Within (PLST) BBD-190"
            ),
        },
    )
    submit = SubmitField("Import Cards")
