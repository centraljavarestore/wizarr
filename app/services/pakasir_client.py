"""
Pakasir Payment Gateway Client

Integrates with Pakasir (https://pakasir.com) for QRIS payment processing.
Uses QuickChart.io for QR code image generation from QR string.

Supports:
- Transaction creation (QRIS / VA)
- Transaction status checking
- Payment simulation (sandbox mode)
- Transaction cancellation
"""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from app.extensions import db
from app.models import PaymentTransaction, Settings, SubscriptionPlan

logger = logging.getLogger("wizarr.pakasir")


def _get_settings() -> dict[str, str]:
    """Load Pakasir settings from Settings table."""
    prefix = "pakasir_"
    keys = ["project_slug", "api_key", "mode", "webhook_url"]
    settings = {}
    for key in keys:
        row = Settings.query.filter_by(key=f"{prefix}{key}").first()
        settings[key] = row.value if row else ""
    return settings


def _generate_order_id() -> str:
    """Generate unique order ID: SUB-YYYYMMDD-XXXXXXXX."""
    date_part = datetime.now(UTC).strftime("%Y%m%d")
    random_part = secrets.token_hex(4).upper()
    return f"SUB-{date_part}-{random_part}"


def create_qris_transaction(
    plan: SubscriptionPlan,
    invitation_id: int | None = None,
) -> PaymentTransaction | None:
    """Create a new QRIS payment transaction via Pakasir API.

    Args:
        plan: The subscription plan to purchase.
        invitation_id: Optional invitation ID to link to this transaction.

    Returns:
        PaymentTransaction with QR data, or None on failure.
    """
    settings = _get_settings()
    project_slug = settings.get("project_slug")
    api_key = settings.get("api_key")
    mode = settings.get("mode", "sandbox")

    if not project_slug or not api_key:
        logger.error("Pakasir not configured: missing project_slug or api_key")
        return None

    order_id = _generate_order_id()
    amount = plan.price

    # Call Pakasir API
    url = "https://app.pakasir.com/api/transactioncreate/qris"
    payload = {
        "project": project_slug,
        "order_id": order_id,
        "amount": amount,
        "api_key": api_key,
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f"Pakasir API error creating transaction: {e}")
        return None
    except (ValueError, KeyError) as e:
        logger.error(f"Pakasir API invalid response: {e}")
        return None

    payment_data = data.get("payment", {})
    if not payment_data:
        logger.error("Pakasir API missing payment data in response")
        return None

    # Parse expiry time
    expired_at = None
    if payment_data.get("expired_at"):
        try:
            expired_at = datetime.fromisoformat(
                payment_data["expired_at"].replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            expired_at = datetime.now(UTC) + timedelta(hours=2)

    # Create transaction record
    tx = PaymentTransaction(
        order_id=order_id,
        amount=payment_data.get("amount", amount),
        fee=payment_data.get("fee"),
        total_payment=payment_data.get("total_payment"),
        payment_method=payment_data.get("payment_method", "qris"),
        qr_string=payment_data.get("payment_number"),
        status="pending",
        expired_at=expired_at,
        subscription_plan_id=plan.id,
        invitation_id=invitation_id,
    )
    db.session.add(tx)
    db.session.commit()

    logger.info(f"Pakasir transaction created: {order_id} = Rp{amount}")
    return tx


def check_transaction_status(
    order_id: str, amount: int
) -> dict[str, Any] | None:
    """Check transaction status with Pakasir API.

    Args:
        order_id: The order ID to check.
        amount: The transaction amount.

    Returns:
        Transaction detail dict or None on failure.
    """
    settings = _get_settings()
    project_slug = settings.get("project_slug")
    api_key = settings.get("api_key")

    if not project_slug or not api_key:
        logger.error("Pakasir not configured")
        return None

    url = (
        f"https://app.pakasir.com/api/transactiondetail"
        f"?project={project_slug}"
        f"&amount={amount}"
        f"&order_id={order_id}"
        f"&api_key={api_key}"
    )

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("transaction")
    except requests.RequestException as e:
        logger.warning(f"Pakasir status check failed for {order_id}: {e}")
        return None


def simulate_payment(order_id: str, amount: int) -> bool:
    """Simulate payment completion (sandbox mode only).

    Args:
        order_id: The order ID to simulate.
        amount: The transaction amount.

    Returns:
        True if simulation succeeded, False otherwise.
    """
    settings = _get_settings()
    project_slug = settings.get("project_slug")
    api_key = settings.get("api_key")
    mode = settings.get("mode", "sandbox")

    if mode != "sandbox":
        logger.warning("Payment simulation only works in sandbox mode")
        return False

    if not project_slug or not api_key:
        logger.error("Pakasir not configured")
        return False

    url = "https://app.pakasir.com/api/paymentsimulation"
    payload = {
        "project": project_slug,
        "order_id": order_id,
        "amount": amount,
        "api_key": api_key,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info(f"Payment simulated for {order_id}")
        return True
    except requests.RequestException as e:
        logger.error(f"Payment simulation failed: {e}")
        return False


def cancel_transaction(order_id: str, amount: int) -> bool:
    """Cancel a pending transaction.

    Args:
        order_id: The order ID to cancel.
        amount: The transaction amount.

    Returns:
        True if cancellation succeeded, False otherwise.
    """
    settings = _get_settings()
    project_slug = settings.get("project_slug")
    api_key = settings.get("api_key")

    if not project_slug or not api_key:
        logger.error("Pakasir not configured")
        return False

    url = "https://app.pakasir.com/api/transactioncancel"
    payload = {
        "project": project_slug,
        "order_id": order_id,
        "amount": amount,
        "api_key": api_key,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info(f"Transaction cancelled: {order_id}")
        return True
    except requests.RequestException as e:
        logger.error(f"Transaction cancellation failed: {e}")
        return False


def get_qr_image_url(qr_string: str, size: int = 300) -> str:
    """Generate QuickChart.io QR code URL from QR string.

    Args:
        qr_string: Raw QR string from Pakasir.
        size: QR code image size in pixels (default: 300).

    Returns:
        QuickChart.io URL for QR code image.
    """
    from urllib.parse import quote

    encoded = quote(qr_string)
    return f"https://quickchart.io/qr?text={encoded}&size={size}&margin=2"


def process_webhook(data: dict[str, Any]) -> tuple[bool, str]:
    """Process incoming Pakasir webhook.

    Validates the webhook payload and updates transaction status.
    Called from the webhook endpoint.

    Args:
        data: Webhook payload from Pakasir.

    Returns:
        Tuple of (success: bool, message: str).
    """
    order_id = data.get("order_id")
    amount = data.get("amount")
    status = data.get("status")
    payment_method = data.get("payment_method")
    completed_at = data.get("completed_at")

    if not order_id or not amount:
        return False, "Missing order_id or amount"

    # Find transaction in DB
    tx = PaymentTransaction.query.filter_by(order_id=order_id).first()
    if not tx:
        return False, f"Transaction not found: {order_id}"

    # Validate amount matches
    if tx.amount != amount:
        return False, f"Amount mismatch for {order_id}"

    # Update transaction
    tx.status = status or "completed"
    tx.payment_method = payment_method or tx.payment_method
    if completed_at:
        try:
            tx.completed_at = datetime.fromisoformat(
                completed_at.replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            tx.completed_at = datetime.now(UTC)

    db.session.commit()
    logger.info(f"Webhook processed: {order_id} -> {status}")
    return True, "Webhook processed"