"""Explicit deterministic support-bot boundary for local demonstrations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SupportBotReply:
    content: str
    provider: str = "demo_support_bot"
    is_demo: bool = True


class DemoSupportBot:
    """Small rules bot; it never represents a connected human support desk."""

    async def reply(self, *, message: str) -> SupportBotReply:
        normalized = message.strip()
        if any(keyword in normalized for keyword in ("投诉", "紧急", "受伤")):
            content = "已记录为优先事项。紧急情况请同时使用景区 SOS 或联系现场工作人员。"
        elif any(keyword in normalized for keyword in ("退款", "取消", "改签")):
            content = "可在对应订单详情提交退改申请, 具体结果以服务端规则校验为准."
        else:
            content = "演示客服已收到消息。可继续描述时间、地点和需要协助的事项。"
        return SupportBotReply(content=content)
