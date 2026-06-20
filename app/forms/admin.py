from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField
from wtforms.validators import DataRequired, EqualTo, Length, Optional, Regexp

from app.forms.validators import (
    USERNAME_ALLOWED_CHARS_MESSAGE,
    USERNAME_LENGTH_MESSAGE,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    USERNAME_PATTERN,
    strip_filter,
)

_username_validators = [
    DataRequired(),
    Length(
        min=USERNAME_MIN_LENGTH,
        max=USERNAME_MAX_LENGTH,
        message=str(_l(USERNAME_LENGTH_MESSAGE)),
    ),
    Regexp(
        USERNAME_PATTERN,
        message=str(_l(USERNAME_ALLOWED_CHARS_MESSAGE)),
    ),
]
_password_validators = [
    DataRequired(),
    Length(min=8, message=str(_l("Password must be at least 8 characters."))),
    Regexp(
        r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).+$",
        message=str(
            _l(
                "Password must contain at least one uppercase letter, one lowercase letter, and one number."
            )
        ),
    ),
]


class AdminCreateForm(FlaskForm):
    username = StringField(
        str(_l("Username")), filters=[strip_filter], validators=_username_validators
    )
    password = PasswordField(str(_l("Password")), validators=_password_validators)
    confirm = PasswordField(
        str(_l("Confirm password")),
        validators=[
            DataRequired(),
            EqualTo("password", message=str(_l("Passwords must match."))),
        ],
    )


class AdminUpdateForm(FlaskForm):
    username = StringField(
        str(_l("Username")), filters=[strip_filter], validators=_username_validators
    )

    # New password can be left blank (unchanged)
    password = PasswordField(
        str(_l("New Password")), validators=[Optional(), *_password_validators[1:]]
    )
    confirm = PasswordField(
        str(_l("Confirm password")),
        validators=[
            Optional(),
            EqualTo("password", message=str(_l("Passwords must match."))),
        ],
    )

    def validate(self, extra_validators=None):
        # Skip inherited validation if confirm required but password empty
        if not super().validate(extra_validators):
            return False
        # If one of password/confirm is filled, both must pass validators
        pw = self.password.data or ""
        if pw and not self.confirm.data:
            self.confirm.errors = [str(_l("Please confirm the new password."))]
            return False
        return True


class SubscriptionPlanForm(FlaskForm):
    name = StringField(
        str(_l("Plan Name")),
        validators=[DataRequired()],
        description=str(_l("e.g. 1 Month, 3 Months, 1 Year")),
    )
    description = StringField(
        str(_l("Description")),
        validators=[Optional()],
        description=str(_l("Short description shown to users")),
    )
    duration_days = StringField(
        str(_l("Duration (days)")),
        validators=[DataRequired()],
        description=str(_l("e.g. 30, 90, 180, 365")),
    )
    price = StringField(
        str(_l("Price (IDR)")),
        validators=[DataRequired()],
        description=str(_l("Price in Indonesian Rupiah. e.g. 25000")),
    )
    sort_order = StringField(
        str(_l("Sort Order")),
        default="0",
        description=str(_l("Lower numbers appear first")),
    )
    is_active = StringField(default="y")  # Simple checkbox value

    def validate_duration_days(self, field):
        try:
            val = int(field.data)
            if val < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError(str(_l("Duration must be a positive whole number (days).")))

    def validate_price(self, field):
        try:
            val = int(field.data)
            if val < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError(str(_l("Price must be a positive whole number (IDR).")))

    def validate_sort_order(self, field):
        if field.data:
            try:
                int(field.data)
            except (ValueError, TypeError):
                raise ValueError(str(_l("Sort order must be a whole number.")))
