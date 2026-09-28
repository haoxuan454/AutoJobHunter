"""Platform-isolated reply senders used by the local conversation center."""

from bosshunter.platform_delivery.reply.boss import send_conversation_reply as send_boss_reply
from bosshunter.platform_delivery.reply.zhilian import send_conversation_reply as send_zhilian_reply

__all__ = ["send_boss_reply", "send_zhilian_reply"]
