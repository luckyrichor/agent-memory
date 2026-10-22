"""Entirely fictional, genuinely distinct full-schema transport controls."""

from typing import Any


def virtual_item(index: int) -> dict[str, Any]:
    if index < 0:
        raise ValueError("nonnegative virtual case index required")
    temporary = index % 2 == 1
    text = (
        f"我今天借用虚构编号{index}的相机，今晚就归还。"
        if temporary
        else f"我从小一直喜欢收集虚构主题{index}的邮票，将来也会长期保持。"
    )
    candidate = (
        f"用户今天借用虚构编号{index}的相机"
        if temporary
        else f"用户长期喜欢收集虚构主题{index}的邮票"
    )
    return {
        "item_id": f"virtual-item-{index}",
        "conversation_id": f"virtual-conversation-{index}",
        "subject": "当前用户",
        "candidate": candidate,
        "source": [
            {
                "source_id": f"virtual-user-turn-{index}",
                "session_id": f"virtual-session-{index}",
                "role": "user",
                "text": text,
            }
        ],
    }
