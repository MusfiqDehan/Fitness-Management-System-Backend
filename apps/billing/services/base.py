"""Abstract base class for payment gateway services."""
from abc import ABC, abstractmethod
from typing import Any, Dict


class AbstractPaymentGateway(ABC):
    """All gateway implementations must satisfy this interface."""

    @abstractmethod
    def initiate(self, transaction) -> Dict[str, Any]:
        """Start a payment session.

        Args:
            transaction: A `PaymentTransaction` instance with at minimum
                `tran_id`, `amount`, `currency`, and `source_payment` set.

        Returns:
            A dict that MUST include ``gateway_url`` — the URL the user
            should be redirected to in order to complete payment.
        """

    @abstractmethod
    def validate(self, val_id: str) -> Dict[str, Any]:
        """Validate a completed payment by the gateway's validation ID.

        Returns:
            A dict with at least ``status`` (gateway-specific string)
            and ``amount`` fields.
        """
