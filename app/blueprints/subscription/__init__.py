"""
Subscription Blueprint

Handles subscription plan selection, QRIS payment, and Pakasir webhook.
User flow: /j/<code> -> /subscribe/<code> (pilih plan) -> /subscribe/pay/<order_id> (QR) -> webhook -> join
"""

from .routes import subscription_bp

__all__ = ["subscription_bp"]