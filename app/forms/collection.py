from flask_wtf import FlaskForm
from wtforms import TextAreaField, StringField, SubmitField
from wtforms.validators import DataRequired, Optional, Length


class ImportForm(FlaskForm):
    physical_location = StringField(
        "Physical Location",
        validators=[Optional(), Length(max=200)],
        render_kw={
            "placeholder": "e.g. Binder 3, Shelf Box A, Sleeve #12…",
            "class": "form-control",
            "maxlength": "200",
        },
    )
    decklist = TextAreaField(
        "Decklist",
        validators=[DataRequired(message="Paste at least one card to import.")],
        render_kw={
            "rows": 18,
            "placeholder": (
                "Paste your card list here — one card per line.\n\n"
                "Supported formats:\n"
                "  4 Lightning Bolt\n"
                "  4x Lightning Bolt\n"
                "  4 Lightning Bolt (M11)\n"
                "  4 Lightning Bolt (LEA) 1\n"
                "  4 Lightning Bolt *F*\n\n"
                "// Comments and blank lines are ignored"
            ),
            "spellcheck": "false",
            "class": "form-control font-monospace",
        },
    )
    submit = SubmitField("Import Cards")
