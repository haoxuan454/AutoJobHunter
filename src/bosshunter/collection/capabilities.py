"""Server-side capability boundaries for platform-specific workflows."""

PLATFORM_CAPABILITIES: dict[str, frozenset[str]] = {
    "boss": frozenset({"collect", "score", "greet", "deliver", "monitor"}),
    #智联首次联系由平台默认招呼流程完成；真实账号闭环验收后开放 deliver。
    #monitor 仍保持关闭，直到智联会话列表轮询与未读同步单独验收。
    "zhilian": frozenset({"collect", "score", "greet", "deliver"}),
    "51job": frozenset({"collect", "score", "greet"}),
    "liepin": frozenset({"collect", "score", "greet", "deliver"}),
}


def platform_supports(platform: str, capability: str) -> bool:
    return capability in PLATFORM_CAPABILITIES.get(str(platform), frozenset())
