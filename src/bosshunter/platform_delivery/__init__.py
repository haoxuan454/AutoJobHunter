"""Platform-specific delivery boundaries.

Collection is shared across platforms, but delivery is not.  Adapters expose a
small contract so a platform can be enabled only after its live DOM and
success signal have been verified independently.
"""

from .base import DeliveryContext, DeliveryResult, get_delivery_adapter

__all__ = ["DeliveryContext", "DeliveryResult", "get_delivery_adapter"]
