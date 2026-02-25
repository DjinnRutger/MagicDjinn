from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, EmailField, SubmitField
from wtforms.validators import DataRequired, Length, Email, EqualTo, Regexp


class SetupForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(3, 64),
            Regexp(r"^[\w.\-]+$", message="Letters, digits, '.', '-' and '_' only."),
        ],
    )
    email = EmailField(
        "Email Address",
        validators=[DataRequired(), Email(), Length(5, 120)],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(8, 128, message="Password must be at least 8 characters."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match.")],
    )
    submit = SubmitField("Create Admin Account")
