"""智联招聘投递适配器。

保持锁定，直到获得当前登录页面的 DOM 证据并完成单条验收。
"""

from .base import UnverifiedDeliveryAdapter


class ZhilianDeliveryAdapter(UnverifiedDeliveryAdapter):
    def __init__(self) -> None:
        super().__init__("zhilian")
