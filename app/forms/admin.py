from flask_wtf import FlaskForm
from wtforms import (
    StringField, PasswordField, BooleanField, SelectField,
    SelectMultipleField, SubmitField, EmailField,
)
from wtforms.validators import DataRequired, Length, Email, Optional, EqualTo, ValidationError
from app.models.user import User


class FriendGroupForm(FlaskForm):
    name       = StringField("Group Name", validators=[DataRequired(), Length(2, 100)])
    member_ids = SelectMultipleField("Members", coerce=int)
    submit     = SubmitField("Save Group")


class UserCreateForm(FlaskForm):
    username         = StringField("Username",         validators=[DataRequired(), Length(3, 64)])
    email            = EmailField("Email",             validators=[DataRequired(), Email(), Length(1, 120)])
    password         = PasswordField("Password",       validators=[DataRequired(), Length(8, 128)])
    confirm_password = PasswordField("Confirm Password", validators=[
        DataRequired(), EqualTo("password", message="Passwords must match.")
    ])
    role_id  = SelectField("Role",          coerce=int, validators=[Optional()])
    is_admin = BooleanField("Administrator")
    is_active = BooleanField("Active", default=True)
    submit   = SubmitField("Create User")

    def validate_username(self, field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError("Username already taken.")

    def validate_email(self, field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError("Email already registered.")


class UserEditForm(FlaskForm):
    username         = StringField("Username", validators=[DataRequired(), Length(3, 64)])
    email            = EmailField("Email",     validators=[DataRequired(), Email(), Length(1, 120)])
    password         = PasswordField("New Password (leave blank to keep current)",
                                     validators=[Optional(), Length(8, 128)])
    confirm_password = PasswordField("Confirm New Password",
                                     validators=[EqualTo("password", message="Passwords must match.")])
    role_id   = SelectField("Role",          coerce=int, validators=[Optional()])
    is_admin  = BooleanField("Administrator")
    is_active = BooleanField("Active")
    submit    = SubmitField("Save Changes")

    def __init__(self, user=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._user = user

    def validate_username(self, field):
        existing = User.query.filter_by(username=field.data).first()
        if existing and (self._user is None or existing.id != self._user.id):
            raise ValidationError("Username already taken.")

    def validate_email(self, field):
        existing = User.query.filter_by(email=field.data).first()
        if existing and (self._user is None or existing.id != self._user.id):
            raise ValidationError("Email already registered.")


class RoleForm(FlaskForm):
    name        = StringField("Role Name",   validators=[DataRequired(), Length(2, 64)])
    description = StringField("Description", validators=[Optional(), Length(0, 255)])
    permissions = SelectMultipleField("Permissions", coerce=int)
    submit      = SubmitField("Save Role")
