"""前程无忧投递适配器，默认安全锁定。"""

from .base import UnverifiedDeliveryAdapter


class Job51DeliveryAdapter(UnverifiedDeliveryAdapter):
    def __init__(self) -> None:
        super().__init__("51job")
