from flask_wtf import FlaskForm
from wtforms import PasswordField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length, Optional


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current Password", validators=[DataRequired()])
    new_password     = PasswordField("New Password",     validators=[Optional(), Length(8, 128)])
    confirm_password = PasswordField("Confirm Password", validators=[EqualTo("new_password", message="Passwords must match.")])
    submit           = SubmitField("Update Password")
