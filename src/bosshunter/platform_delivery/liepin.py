"""猎聘投递适配器，默认安全锁定。"""

from .base import UnverifiedDeliveryAdapter


class LiepinDeliveryAdapter(UnverifiedDeliveryAdapter):
    def __init__(self) -> None:
        super().__init__("liepin")
