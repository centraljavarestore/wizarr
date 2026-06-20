"""
Subscription routes for user-facing flow:
- GET /subscribe/<invite_code> → show plan selection
- POST /subscribe/<invite_code> → create transaction, redirect to payment
- GET /subscribe/pay/<order_id> → show QR code
- GET /subscribe/status/<order_id> → AJAX polling endpoint
- POST /subscribe/webhook/pakasir → Pakasir webhook
- GET /subscribe/simulate/<order_id> → sandbox payment simulation
"""

import logging
from datetime import UTC, datetime

import requests
from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import _
from flask_login import current_user

from app.extensions import db
from app.models import (
    Invitation,
    PaymentTransaction,
    Settings,
    SubscriptionPlan,
)
from app.services.invite_code_manager import InviteCodeManager
from app.services.pakasir_client import (
    check_transaction_status,
    create_qris_transaction,
    get_qr_image_url,
    process_webhook,
    simulate_payment,
)

logger = logging.getLogger("wizarr.subscription")

subscription_bp = Blueprint("subscription", __name__, url_prefix="/subscribe")


def _has_active_plans() -> bool:
    """Check if there are any active subscription plans configured."""
    return SubscriptionPlan.query.filter_by(is_active=True).count() > 0


def _get_pakasir_settings() -> dict[str, str]:
    """Get Pakasir configuration from Settings table."""
    keys = ["pakasir_project_slug", "pakasir_api_key", "pakasir_mode"]
    result = {}
    for key in keys:
        row = Settings.query.filter_by(key=key).first()
        result[key] = row.value if row else ""
    return result


@subscription_bp.route("/<invite_code>", methods=["GET", "POST"])
def plans(invite_code: str):
    """Show subscription plan selection or process plan selection."""
    # Validate invite code
    is_valid, invitation = InviteCodeManager.validate_invite_code(invite_code)
    if not is_valid or not invitation:
        return render_template("invalid-invite.html", error=_("Invalid or expired invitation"))

    # Check if subscription system has active plans
    if not _has_active_plans():
        # No plans configured — skip to join page directly
        return redirect(url_for("public.invite", code=invite_code))

    # Get Pakasir settings
    pakasir = _get_pakasir_settings()
    if not pakasir.get("pakasir_project_slug") or not pakasir.get("pakasir_api_key"):
        return render_template(
            "invalid-invite.html",
            error=_("Payment system not configured. Please contact the administrator."),
        )

    if request.method == "POST":
        # User selected a plan — create transaction
        plan_id = request.form.get("plan_id")
        if not plan_id or not plan_id.isdigit():
            return render_template(
                "subscription/plans.html",
                plans=SubscriptionPlan.query.filter_by(is_active=True)
                .order_by(SubscriptionPlan.sort_order)
                .all(),
                invite_code=invite_code,
                error=_("Please select a subscription plan."),
            )

        plan = db.session.get(SubscriptionPlan, int(plan_id))
        if not plan or not plan.is_active:
            return render_template(
                "subscription/plans.html",
                plans=SubscriptionPlan.query.filter_by(is_active=True)
                .order_by(SubscriptionPlan.sort_order)
                .all(),
                invite_code=invite_code,
                error=_("Invalid plan selected."),
            )

        # Create QRIS transaction via Pakasir
        tx = create_qris_transaction(plan, invitation_id=invitation.id)
        if not tx:
            return render_template(
                "subscription/plans.html",
                plans=SubscriptionPlan.query.filter_by(is_active=True)
                .order_by(SubscriptionPlan.sort_order)
                .all(),
                invite_code=invite_code,
                error=_("Failed to create payment. Please try again."),
            )

        # Store in session: which plan & invite code
        session["subscription_plan_id"] = plan.id
        session["subscription_invite_code"] = invite_code
        session["subscription_order_id"] = tx.order_id

        # Redirect to payment page
        return redirect(url_for("subscription.payment", order_id=tx.order_id))

    # GET — show plan selection
    plans = (
        SubscriptionPlan.query.filter_by(is_active=True)
        .order_by(SubscriptionPlan.sort_order)
        .all()
    )
    return render_template(
        "subscription/plans.html",
        plans=plans,
        invite_code=invite_code,
        pakasir_mode=pakasir.get("pakasir_mode", "sandbox"),
    )


@subscription_bp.route("/pay/<order_id>")
def payment(order_id: str):
    """Show payment page with QR code."""
    tx = PaymentTransaction.query.filter_by(order_id=order_id).first()
    if not tx:
        abort(404)

    # If already completed, skip to join
    if tx.status == "completed":
        return redirect(url_for("public.invite", code=tx.invitation.code if tx.invitation else ""))

    # Generate QR image URL from QR string
    qr_image_url = ""
    if tx.qr_string:
        qr_image_url = get_qr_image_url(tx.qr_string)

    # Get Pakasir mode for display
    pakasir = _get_pakasir_settings()
    mode = pakasir.get("pakasir_mode", "sandbox")

    return render_template(
        "subscription/payment.html",
        transaction=tx,
        qr_image_url=qr_image_url,
        pakasir_mode=mode,
    )


@subscription_bp.route("/status/<order_id>")
def payment_status(order_id: str):
    """AJAX endpoint to check payment status (polled by frontend)."""
    tx = PaymentTransaction.query.filter_by(order_id=order_id).first()
    if not tx:
        return jsonify({"status": "not_found"}), 404

    # Poll Pakasir API for status update
    remote = check_transaction_status(order_id, tx.amount)
    if remote and remote.get("status") == "completed":
        # Update local status
        if tx.status != "completed":
            tx.status = "completed"
            tx.payment_method = remote.get("payment_method", tx.payment_method)
            if remote.get("completed_at"):
                try:
                    tx.completed_at = datetime.fromisoformat(
                        remote["completed_at"].replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    tx.completed_at = datetime.now(UTC)
            db.session.commit()

            # Set session flag so user can proceed to join
            session["payment_completed"] = True
            session["payment_order_id"] = order_id

        return jsonify({"status": "completed", "redirect": url_for("public.invite", code=tx.invitation.code if tx.invitation else "")})

    if remote and remote.get("status") == "failed":
        tx.status = "failed"
        db.session.commit()
        return jsonify({"status": "failed"})

    # Check if transaction expired
    if tx.expired_at and tx.expired_at < datetime.now(UTC):
        tx.status = "expired"
        db.session.commit()
        return jsonify({"status": "expired"})

    return jsonify({"status": "pending", "expired_at": tx.expired_at.isoformat() if tx.expired_at else None})


@subscription_bp.route("/webhook/pakasir", methods=["POST"])
def pakasir_webhook():
    """Receive payment notification from Pakasir.

    Pakasir will POST here when a payment is completed.
    Expected payload:
    {
        "amount": 25000,
        "order_id": "SUB-20260620-XXXX",
        "project": "myproject",
        "status": "completed",
        "payment_method": "qris",
        "completed_at": "2024-09-10T08:07:02.819+07:00"
    }
    """
    data = request.get_json(silent=True)
    if not data:
        logger.warning("Pakasir webhook: empty body")
        return "empty body", 400

    logger.info(f"Pakasir webhook received: {data}")

    success, message = process_webhook(data)
    if success:
        return jsonify({"status": "ok"}), 200

    logger.warning(f"Pakasir webhook rejected: {message}")
    return jsonify({"error": message}), 400


@subscription_bp.route("/simulate/<order_id>", methods=["POST"])
def simulate(order_id: str):
    """Simulate a payment (sandbox mode only)."""
    tx = PaymentTransaction.query.filter_by(order_id=order_id).first()
    if not tx:
        abort(404)

    success = simulate_payment(order_id, tx.amount)
    if success:
        tx.status = "completed"
        tx.completed_at = datetime.now(UTC)
        db.session.commit()
        session["payment_completed"] = True
        session["payment_order_id"] = order_id
        return jsonify({"status": "completed"})

    return jsonify({"error": "Simulation failed"}), 500