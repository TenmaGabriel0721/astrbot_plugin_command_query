import collections
import json
from collections.abc import AsyncGenerator
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star import command_management


@register(
    "astrbot_plugin_command_query",
    "TenmaGabriel0721",
    "让LLM能够实时查询指令信息，引导用户正确使用",
    "2.1.2",
)
class CommandQueryPlugin(Star):
    """
    AstrBot 指令查询插件 v2.1.2

    【核心功能】
    为 LLM 提供指令查询能力，让 LLM 能够：
    1. 纠正用户输入的错误指令
    2. 引导用户正确使用功能
    3. 推荐相关指令

    【应用场景】
    - 用户输错指令时，LLM 查询正确写法并纠正
    - 用户不知道怎么用时，LLM 查询用法并引导
    - 用户找功能时，LLM 搜索相关指令并推荐

    【实现要点】
    - 使用 AstrBot 指令管理接口读取当前生效指令
    - 跟随后台重命名、禁用、别名和权限配置
    - 别名只用于匹配，结果聚合到主命令
    """

    def __init__(self, context: Context, config: AstrBotConfig = None):
        """插件初始化"""
        super().__init__(context)
        self.config = config
        # 获取用户配置的指令前缀，默认为 /
        self.command_prefix = config.get("command_prefix", "/") if config else "/"
        logger.info(f"指令查询插件已加载 v2.1.2 (指令前缀: {self.command_prefix})")

    def _replace_prefix(self, command: str) -> str:
        """
        将指令中的 / 前缀替换为用户配置的前缀

        Args:
            command: 原始指令（如 "/钓鱼"）

        Returns:
            替换后的指令（如 "~钓鱼"）
        """
        if command.startswith("/"):
            return self.command_prefix + command[1:]
        return command

    def _normalize_command(self, command: str) -> str:
        """标准化为内部使用的 /command 形式。"""
        command = " ".join((command or "").strip().split())
        if not command:
            return ""
        if command.startswith(self.command_prefix) and self.command_prefix != "/":
            command = "/" + command[len(self.command_prefix) :].lstrip()
        if not command.startswith("/"):
            command = "/" + command
        return command

    def _unwrap_message_event(
        self,
        event_or_context: Any,
    ) -> AstrMessageEvent | None:
        """Extract the real message event from LLM tool context wrappers.

        Args:
            event_or_context: A direct message event or a nested tool context.

        Returns:
            The message event containing a unified message origin, or None when
            no valid event can be found.
        """
        candidates = [event_or_context]
        seen = set()

        while candidates:
            candidate = candidates.pop(0)
            if candidate is None:
                continue

            marker = id(candidate)
            if marker in seen:
                continue
            seen.add(marker)

            if getattr(candidate, "unified_msg_origin", None):
                return candidate

            inner_context = getattr(candidate, "context", None)
            if inner_context is not None:
                candidates.append(getattr(inner_context, "event", None))
                candidates.append(inner_context)

            candidates.append(getattr(candidate, "event", None))

        return None

    def _compose_alias(self, parent_signature: str, alias: str) -> str:
        alias = " ".join((alias or "").strip().split())
        parent_signature = " ".join((parent_signature or "").strip().split())
        if not alias:
            return ""
        if parent_signature and not alias.startswith(parent_signature + " "):
            return f"{parent_signature} {alias}"
        return alias

    def _iter_command_items(self, items: list[dict[str, Any]]):
        for item in items:
            yield item
            sub_commands = item.get("sub_commands") or []
            if sub_commands:
                yield from self._iter_command_items(sub_commands)

    def _get_active_module_paths(self) -> set[str]:
        try:
            return {
                star.module_path
                for star in self.context.get_all_stars()
                if star.activated and star.module_path
            }
        except Exception as e:
            logger.error(f"获取激活插件列表失败: {e}")
            return set()

    async def _get_all_commands(
        self,
        event: Any,
    ) -> dict[str, dict]:
        """获取当前事件可用的指令信息。

        使用 AstrBot 的 command_management.list_commands() 作为数据源，确保后台重命名、
        禁用、别名和权限配置都会被应用。别名只作为主命令的匹配字段，不作为独立结果返回。

        Args:
            event: 当前消息事件或工具上下文，用于按会话读取对应配置的插件选择范围。

        Returns:
            以标准化命令名为键的可用指令信息。
        """
        commands_dict = {}

        try:
            command_items = await command_management.list_commands()
        except Exception as e:
            logger.error(f"获取指令列表失败: {e}")
            return {}

        active_module_paths = self._get_active_module_paths()
        message_event = self._unwrap_message_event(event)
        if message_event is None:
            error = "无法从工具上下文提取当前消息事件"
            logger.error(error)
            raise ValueError(error)

        try:
            current_config = self.context.get_config(message_event.unified_msg_origin)
            plugin_set = current_config.get("plugin_set", ["*"])
        except Exception as e:
            logger.error(f"获取当前会话配置失败: {e}")
            raise

        selected_plugins = (
            None
            if not isinstance(plugin_set, list) or "*" in plugin_set
            else {str(plugin_name) for plugin_name in plugin_set}
        )

        for item in self._iter_command_items(command_items):
            if not item.get("enabled", True):
                continue
            module_path = item.get("module_path", "")
            if module_path not in active_module_paths:
                continue

            plugin_name = item.get("plugin") or "未知插件"
            if (
                selected_plugins is not None
                and not item.get("reserved", False)
                and plugin_name not in selected_plugins
            ):
                continue
            # 跳过核心插件和自身，避免 LLM 把辅助命令推荐给用户。
            if plugin_name in [
                "astrbot",
                "astrbot_plugin_command_query",
                "astrbot-reminder",
            ]:
                continue

            command = (
                item.get("effective_command")
                or item.get("original_command")
                or item.get("handler_name")
                or ""
            )
            primary_command = self._normalize_command(command)
            if not primary_command:
                continue

            aliases = []
            parent_signature = item.get("parent_signature") or ""
            for alias in item.get("aliases") or []:
                normalized_alias = self._normalize_command(
                    self._compose_alias(parent_signature, str(alias))
                )
                if normalized_alias and normalized_alias != primary_command:
                    aliases.append(normalized_alias)

            # command_management 已经应用了命令配置，这里只保留主命令入口。
            commands_dict[primary_command] = {
                "command": primary_command,
                "description": item.get("description") or "无描述",
                "plugin": plugin_name,
                "plugin_display_name": item.get("plugin_display_name"),
                "aliases": sorted(set(aliases)),
                "is_admin": item.get("permission") == "admin",
                "command_id": item.get("handler_full_name") or primary_command,
                "command_type": item.get("type") or "command",
            }

        logger.info(f"已读取 {len(commands_dict)} 个当前生效指令（别名已聚合）")
        return commands_dict

    async def _search_similar_commands(
        self,
        event: AstrMessageEvent,
        keyword: str,
        limit: int = 5,
    ) -> list[dict]:
        """搜索当前事件可用的相似指令。

        别名用于匹配，但结果始终返回主命令，避免别名成为重复候选。

        Args:
            event: 当前消息事件，用于限定可用插件范围。
            keyword: 指令名、别名、描述或插件名关键词。
            limit: 最多返回的匹配数量。

        Returns:
            按匹配优先级排列的指令信息。
        """
        all_commands = await self._get_all_commands(event)
        keyword_lower = keyword.lower().strip()

        # 移除开头的指令前缀
        if self.command_prefix != "/" and keyword_lower.startswith(self.command_prefix):
            keyword_lower = keyword_lower[len(self.command_prefix) :].strip()
        if keyword_lower.startswith("/"):
            keyword_lower = keyword_lower[1:].strip()

        results = []
        seen = set()

        def add_result(cmd_info: dict, matched_alias: str = ""):
            command_id = cmd_info.get("command_id") or cmd_info["command"]
            if command_id in seen:
                return
            seen.add(command_id)
            if matched_alias:
                cmd_info = {**cmd_info, "matched_alias": matched_alias}
            results.append(cmd_info)

        # 1. 精确匹配
        exact_match = f"/{keyword_lower}"
        if exact_match in all_commands:
            add_result(all_commands[exact_match])

        # 2. 别名精确匹配
        for cmd_info in all_commands.values():
            for alias in cmd_info["aliases"]:
                if exact_match == alias.lower():
                    add_result(cmd_info, matched_alias=alias)

        # 3. 模糊匹配 - 命令名或别名包含关键词
        for cmd_name, cmd_info in all_commands.items():
            cmd_name_lower = cmd_name.lower()
            if keyword_lower in cmd_name_lower:
                add_result(cmd_info)
                continue

            for alias in cmd_info["aliases"]:
                if keyword_lower in alias.lower():
                    add_result(cmd_info, matched_alias=alias)
                    break

        # 4. 描述匹配 - 描述包含关键词
        if len(results) < limit:
            for cmd_info in all_commands.values():
                desc_lower = cmd_info["description"].lower()
                if keyword_lower in desc_lower:
                    add_result(cmd_info)

                if len(results) >= limit:
                    break

        # 5. 插件名匹配
        if len(results) < limit:
            for cmd_info in all_commands.values():
                plugin_lower = cmd_info["plugin"].lower()
                if keyword_lower in plugin_lower:
                    add_result(cmd_info)

                if len(results) >= limit:
                    break

        return results[:limit]

    def _find_command(
        self, all_commands: dict[str, dict], command_name: str
    ) -> dict | None:
        """按主命令或别名查找，命中别名时仍返回主命令信息。"""
        if command_name in all_commands:
            return all_commands[command_name]
        for cmd_info in all_commands.values():
            if command_name in cmd_info["aliases"]:
                return cmd_info
        return None

    @filter.llm_tool(name="search_command")
    async def search_command(self, event: AstrMessageEvent, **kwargs) -> str:
        """🔍 【优先使用】模糊搜索指令 - 万能查询工具

        ⚠️ 这是最常用的工具！几乎所有指令查询场景都应该用这个！

        【必须使用的场景】
        1. 用户输错指令（如 "/钩鱼"、"/抽将"）→ 用这个纠正
        2. 用户询问功能（如 "有抽奖吗"、"能钓鱼吗"）→ 用这个搜索
        3. 用户描述需求（如 "我想玩游戏"）→ 用这个查找
        4. 用户想知道某个插件有什么功能 → 用这个搜索插件名

        【禁止重复调用】
        - 调用一次后，已经获得足够信息，不要再调用其他工具！
        - 搜索结果包含指令名、描述、插件名、别名，信息已经很完整
        - 如果用户追问"怎么用"，再考虑用 get_command_detail

        Args:
            keyword(string): 搜索关键词（指令名/功能词/插件名的任意部分）

        返回:
            JSON格式，包含最多5条匹配的指令（已包含描述和别名）

        示例:
            用户："有钓鱼吗" → search_command(keyword="钓鱼") → 直接返回答案，不要再调用其他工具！
        """
        try:
            keyword = kwargs.get("keyword", "")
            if not keyword:
                return json.dumps(
                    {
                        "success": False,
                        "message": "缺少必需参数: keyword",
                        "results": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            logger.info(f"LLM搜索指令: {keyword}")

            results = await self._search_similar_commands(event, keyword, limit=5)

            if not results:
                return json.dumps(
                    {
                        "success": False,
                        "message": f"未找到与 '{keyword}' 相关的指令",
                        "results": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            # 清理结果，移除内部字段，并替换前缀
            clean_results = []
            for result in results:
                clean_result = {
                    "command": self._replace_prefix(result["command"]),
                    "description": result["description"],
                    "plugin": result["plugin"],
                    "aliases": [
                        self._replace_prefix(alias) for alias in result["aliases"]
                    ],
                    "is_admin": result.get("is_admin", False),
                    "command_id": result.get("command_id", ""),
                }
                if result.get("matched_alias"):
                    clean_result["matched_alias"] = self._replace_prefix(
                        result["matched_alias"]
                    )
                clean_results.append(clean_result)

            logger.info(f"找到 {len(clean_results)} 条相关指令")
            return json.dumps(
                {
                    "success": True,
                    "message": f"找到 {len(clean_results)} 条与 '{keyword}' 相关的指令",
                    "results": clean_results,
                },
                ensure_ascii=False,
                indent=2,
            )

        except Exception as e:
            logger.error(f"搜索指令时发生错误: {e}")
            return json.dumps(
                {"success": False, "message": f"搜索失败: {str(e)}", "results": []},
                ensure_ascii=False,
                indent=2,
            )

    @filter.llm_tool(name="get_command_detail")
    async def get_command_detail(self, event: AstrMessageEvent, **kwargs) -> str:
        """📖 【仅在必要时使用】获取指令详细用法

        ⚠️ 慎用！只在用户明确询问"怎么用"时才调用！

        【何时使用】
        1. 用户明确问"XX指令怎么用"、"XX怎么操作"
        2. 用户问"XX需要什么参数"
        3. 已通过 search_command 找到指令，用户追问具体用法

        【何时不用】
        ❌ 用户只是问"有XX功能吗" → 用 search_command 就够了！
        ❌ 用户问"能不能XX" → 用 search_command 就够了！
        ❌ 已经调用过 search_command → 不要再调用这个！除非用户追问

        【避免浪费】
        - search_command 的结果已经包含描述，通常够用了
        - 只有用户明确需要详细用法时才调用此工具

        Args:
            command_name(string): 指令名（可带或不带前缀）

        返回:
            JSON格式，包含指令详情和相关推荐
        """
        try:
            command_name = kwargs.get("command_name", "")
            if not command_name:
                return json.dumps(
                    {"success": False, "message": "缺少必需参数: command_name"},
                    ensure_ascii=False,
                    indent=2,
                )

            logger.info(f"LLM查询指令详情: {command_name}")

            # 标准化指令名
            command_name = self._normalize_command(command_name)

            all_commands = await self._get_all_commands(event)

            # 查找指令
            cmd_info = self._find_command(all_commands, command_name)
            if not cmd_info:
                # 尝试搜索相似指令
                similar = await self._search_similar_commands(
                    event,
                    command_name,
                    limit=3,
                )
                return json.dumps(
                    {
                        "success": False,
                        "message": f"未找到指令 '{command_name}'",
                        "suggestions": [
                            self._replace_prefix(cmd["command"]) for cmd in similar
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            # 查找同插件的其他指令（相关推荐）
            plugin_name = cmd_info["plugin"]
            similar_commands = []
            for cmd_name, cmd_data in all_commands.items():
                if cmd_data["plugin"] == plugin_name and cmd_name != command_name:
                    similar_commands.append(cmd_name)
                    if len(similar_commands) >= 3:
                        break

            result = {
                "success": True,
                "command": self._replace_prefix(cmd_info["command"]),
                "description": cmd_info["description"],
                "plugin": cmd_info["plugin"],
                "aliases": [
                    self._replace_prefix(alias) for alias in cmd_info["aliases"]
                ],
                "is_admin": cmd_info.get("is_admin", False),
                "command_id": cmd_info.get("command_id", ""),
                "similar_commands": [
                    self._replace_prefix(cmd) for cmd in similar_commands
                ],
            }

            logger.info(f"成功获取指令详情: {command_name}")
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"查询指令详情时发生错误: {e}")
            return json.dumps(
                {"success": False, "message": f"查询失败: {str(e)}"},
                ensure_ascii=False,
                indent=2,
            )

    @filter.llm_tool(name="list_plugin_commands")
    async def list_plugin_commands(self, event: AstrMessageEvent, **kwargs) -> str:
        """📦 【特殊场景使用】列出插件清单

        ⚠️ 仅在用户明确要"看插件列表"时才用！大多数情况用 search_command 更好！

        【何时使用】
        1. 用户明确问"有哪些插件"、"插件列表"
        2. 用户问"一共多少个插件"
        3. 用户要"看看都有什么插件"

        【何时不用】
        ❌ 用户问"有XX功能吗" → 用 search_command！
        ❌ 用户问"能不能XX" → 用 search_command！
        ❌ 用户想知道某个插件的功能 → 用 search_command(keyword="插件名")！

        【避免浪费】
        - 如果用户只是想找某个功能，search_command 更合适
        - 只返回插件名列表，没有指令详情，用处有限
        - 除非用户明确要看插件清单，否则不要用这个

        Args:
            plugin_name(string): 【可选】不传=列出所有插件名；传入=列出该插件的指令

        返回:
            JSON格式的插件列表或插件指令列表

        示例:
            用户："有哪些插件" → list_plugin_commands()
            但如果用户问："有钓鱼功能吗" → 用 search_command(keyword="钓鱼")！
        """
        try:
            plugin_name = kwargs.get("plugin_name", "")
            logger.info(f"LLM查询插件指令: {plugin_name or '所有插件'}")

            all_commands = await self._get_all_commands(event)

            # 按插件分组
            plugins_dict = collections.defaultdict(list)
            for cmd_info in all_commands.values():
                plugins_dict[cmd_info["plugin"]].append(cmd_info)

            # 如果没有指定插件名，返回所有插件列表
            if not plugin_name:
                plugin_list = sorted(plugins_dict.keys())
                return json.dumps(
                    {
                        "success": True,
                        "message": f"系统共有 {len(plugin_list)} 个插件",
                        "plugins": plugin_list,
                        "hint": "使用 list_plugin_commands 并指定 plugin_name 参数查看具体插件的指令",
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            # 搜索匹配的插件（支持模糊匹配）
            plugin_name_lower = plugin_name.lower()
            matched_plugin = None
            for pname in plugins_dict.keys():
                if plugin_name_lower in pname.lower():
                    matched_plugin = pname
                    break

            if not matched_plugin:
                return json.dumps(
                    {
                        "success": False,
                        "message": f"未找到插件 '{plugin_name}'",
                        "available_plugins": sorted(plugins_dict.keys()),
                    },
                    ensure_ascii=False,
                    indent=2,
                )

            # 获取该插件的所有指令
            commands = plugins_dict[matched_plugin]

            result = {
                "success": True,
                "plugin": matched_plugin,
                "command_count": len(commands),
                "commands": [
                    {
                        "command": self._replace_prefix(cmd["command"]),
                        "description": cmd["description"],
                        "aliases": [
                            self._replace_prefix(alias) for alias in cmd["aliases"]
                        ],
                        "is_admin": cmd.get("is_admin", False),
                        "command_id": cmd.get("command_id", ""),
                    }
                    for cmd in commands
                ],
            }

            logger.info(f"找到插件 '{matched_plugin}' 的 {len(commands)} 条指令")
            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"查询插件指令时发生错误: {e}")
            return json.dumps(
                {"success": False, "message": f"查询失败: {str(e)}"},
                ensure_ascii=False,
                indent=2,
            )

    @filter.command("指令查询帮助", alias={"query_help"})
    async def help_command(
        self, event: AstrMessageEvent
    ) -> AsyncGenerator[MessageEventResult, None]:
        """显示插件帮助信息"""
        help_text = """=== 指令查询插件 v2.1.2 ===
👩‍💻 by 珈百璃

【核心功能】
为 LLM 提供实时指令查询能力，让 LLM 能够：
✅ 纠正用户输入的错误指令
✅ 引导用户正确使用功能
✅ 推荐相关指令

【LLM 工具函数】
1️⃣ search_command(keyword)
   搜索指令，支持模糊匹配
   场景：用户输错指令、找功能

2️⃣ get_command_detail(command_name)
   查询指令详情和用法
   场景：用户问怎么用某个指令

3️⃣ list_plugin_commands(plugin_name)
   列举插件的所有指令
   场景：用户问某个插件有什么功能

【应用场景示例】
🔹 用户：/钩鱼
   LLM：[调用 search_command("钩鱼")]
   LLM：姐姐是 /钓鱼 哦，不是钩鱼～

🔹 用户：怎么玩钓鱼
   LLM：[调用 get_command_detail("/钓鱼")]
   LLM：钓鱼游戏使用 /钓鱼 开始...

🔹 用户：有没有抽奖功能
   LLM：[调用 search_command("抽奖")]
   LLM：有的！可以用 /抽奖 参与...

【可用命令】
/指令查询帮助         - 显示本帮助

【设计理念】
精简实用，只返回必要信息
跟随后台命令配置
别名聚合到主命令，减少重复候选
让 LLM 成为用户的指令助手

【数据来源】
✅ 使用 AstrBot command_management.list_commands()
✅ 自动过滤禁用命令
✅ 返回 command_id 供 LLM 区分相似指令"""

        yield event.plain_result(help_text)

    async def terminate(self) -> None:
        """插件卸载时调用"""
        logger.info("指令查询插件已卸载")
