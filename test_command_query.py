import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot.core.agent.run_context import ContextWrapper
from data.plugins.astrbot_plugin_command_query import main as command_query


@pytest.mark.asyncio
async def test_context_wrapper_filters_commands_per_profile(monkeypatch):
    command_items = [
        {
            "enabled": True,
            "module_path": "plugins.gemini",
            "plugin": "astrbot_plugin_gemini_image",
            "effective_command": "/充值",
            "description": "充值画图积分",
            "aliases": [],
            "handler_full_name": "plugins.gemini.recharge",
        },
        {
            "enabled": True,
            "module_path": "plugins.music",
            "plugin": "astrbot_plugin_music",
            "effective_command": "/点歌",
            "description": "点歌",
            "aliases": [],
            "handler_full_name": "plugins.music.song",
        },
    ]
    monkeypatch.setattr(
        command_query.command_management,
        "list_commands",
        AsyncMock(return_value=command_items),
    )

    profiles = {
        "umo:a": {"plugin_set": ["astrbot_plugin_gemini_image"]},
        "umo:b": {"plugin_set": ["astrbot_plugin_music"]},
    }
    context = MagicMock()
    context.get_config.side_effect = profiles.__getitem__
    context.get_all_stars.return_value = [
        SimpleNamespace(activated=True, module_path="plugins.gemini"),
        SimpleNamespace(activated=True, module_path="plugins.music"),
    ]
    plugin = command_query.CommandQueryPlugin(
        context,
        {"command_prefix": "~"},
    )

    def wrapped_event(umo: str) -> ContextWrapper:
        event = SimpleNamespace(unified_msg_origin=umo)
        return ContextWrapper(context=SimpleNamespace(event=event))

    profile_a = json.loads(
        await plugin.search_command(wrapped_event("umo:a"), keyword="充值")
    )
    profile_b_own = json.loads(
        await plugin.search_command(wrapped_event("umo:b"), keyword="点歌")
    )
    profile_b_filtered = json.loads(
        await plugin.search_command(wrapped_event("umo:b"), keyword="充值")
    )

    assert profile_a["success"] is True
    assert profile_a["results"][0]["command"] == "~充值"
    assert profile_b_own["success"] is True
    assert profile_b_own["results"][0]["command"] == "~点歌"
    assert profile_b_filtered["success"] is False
    assert profile_b_filtered["results"] == []
    assert [call.args[0] for call in context.get_config.call_args_list] == [
        "umo:a",
        "umo:b",
        "umo:b",
    ]


@pytest.mark.asyncio
async def test_invalid_tool_context_returns_query_error(monkeypatch):
    monkeypatch.setattr(
        command_query.command_management,
        "list_commands",
        AsyncMock(return_value=[]),
    )
    context = MagicMock()
    context.get_all_stars.return_value = []
    plugin = command_query.CommandQueryPlugin(
        context,
        {"command_prefix": "~"},
    )

    cyclic_context = SimpleNamespace()
    cyclic_context.context = cyclic_context
    result = json.loads(await plugin.search_command(cyclic_context, keyword="充值"))

    assert result["success"] is False
    assert "无法从工具上下文提取当前消息事件" in result["message"]
    context.get_config.assert_not_called()
