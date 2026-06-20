from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, StringField
from wtforms.validators import DataRequired, Optional


class GeneralSettingsForm(FlaskForm):
    server_name = StringField("Display Name", validators=[DataRequired()])
    wizard_acl_enabled = BooleanField(
        "Protect Wizard Access", default=True, validators=[Optional()]
    )
    expiry_action = SelectField(
        "Expiry Action",
        choices=[
            ("delete", "Delete User"),
            ("disable", "Disable User (if supported)"),
        ],
        default="delete",
        validators=[DataRequired()],
    )

    # ── Pakasir Payment Gateway ────────────────────────────────────
    pakasir_project_slug = StringField(
        "Pakasir Project Slug",
        validators=[Optional()],
        description="Your project slug from app.pakasir.com",
    )
    pakasir_api_key = StringField(
        "Pakasir API Key",
        validators=[Optional()],
        description="API Key from your Pakasir project",
    )
    pakasir_mode = SelectField(
        "Pakasir Mode",
        choices=[("sandbox", "Sandbox (Testing)"), ("production", "Production")],
        default="sandbox",
        validators=[DataRequired()],
        description="Sandbox for testing, Production for live payments",
    )
