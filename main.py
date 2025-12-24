
import json
import collections
from typing import Dict, List, Optional, AsyncGenerator
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.star.filter.command import CommandFilter
from astrbot.core.star.filter.command_group import CommandGroupFilter
from astrbot.core.star.star_handler import star_handlers_registry, StarHandlerMetadata


@register(
    "astrbot_plugin_command_query",
    "珈百璃",
    "让LLM能够实时查询指令信息，引导用户正确使用",
    "2.0.0"
)
class CommandQueryPlugin(Star):
    """
    AstrBot 指令查询插件 v2.0
    
    【核心功能】
    为 LLM 提供指令查询能力，让 LLM 能够：
    1. 纠正用户输入的错误指令
    2. 引导用户正确使用功能
    3. 推荐相关指令
    
    【应用场景】
    - 用户输错指令时，LLM 查询正确写法并纠正
    - 用户不知道怎么用时，LLM 查询用法并引导
    - 用户找功能时，LLM 搜索相关指令并推荐
    """
    
    def __init__(self, context: Context, config: AstrBotConfig = None):
        """插件初始化"""
        super().__init__(context)
        self.config = config
        self._command_cache = None  # 指令缓存
        # 获取用户配置的指令前缀，默认为 /
        self.command_prefix = config.get("command_prefix", "/") if config else "/"
        logger.info(f"指令查询插件已加载 v2.0 - LLM实时助手模式 (指令前缀: {self.command_prefix})")

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
    
    def _get_all_commands(self) -> Dict[str, Dict]:
        """
        获取所有指令信息并缓存
        
        返回格式: {
            "/钓鱼": {
                "command": "/钓鱼",
                "description": "开始钓鱼游戏",
                "plugin": "钓鱼游戏插件",
                "aliases": ["/fishing", "/fish"]
            }
        }
        """
        if self._command_cache is not None:
            return self._command_cache
        
        commands_dict = {}
        
        try:
            # 获取所有已激活的插件
            all_stars = self.context.get_all_stars()
            all_stars = [star for star in all_stars if star.activated]
        except Exception as e:
            logger.error(f"获取插件列表失败: {e}")
            return {}
        
        if not all_stars:
            logger.warning("没有找到任何激活的插件")
            return {}
        
        # 遍历所有插件
        for star in all_stars:
            plugin_name = getattr(star, "name", "未知插件")
            module_path = getattr(star, "module_path", None)
            
            # 跳过核心插件和自身
            if plugin_name in ["astrbot", "astrbot_plugin_command_query", "astrbot-reminder"]:
                continue
            
            if not module_path:
                continue
            
            # 遍历所有注册的处理器
            for handler in star_handlers_registry:
                if not isinstance(handler, StarHandlerMetadata):
                    continue
                
                # 检查此处理器是否属于当前插件
                if handler.handler_module_path != module_path:
                    continue
                
                command_name = None
                aliases = []
                description = handler.desc or "无描述"
                
                # 查找命令过滤器
                for filter_ in handler.event_filters:
                    if isinstance(filter_, CommandFilter):
                        command_name = filter_.command_name
                        # 获取别名
                        if hasattr(filter_, 'alias') and filter_.alias:
                            if isinstance(filter_.alias, set):
                                aliases = list(filter_.alias)
                            elif isinstance(filter_.alias, list):
                                aliases = filter_.alias
                        break
                    elif isinstance(filter_, CommandGroupFilter):
                        command_name = filter_.group_name
                        break
                
                # 如果找到了命令，添加到字典
                if command_name:
                    # 确保命令以 / 开头
                    if not command_name.startswith("/"):
                        command_name = "/" + command_name
                    
                    command_info = {
                        "command": command_name,
                        "description": description,
                        "plugin": plugin_name,
                        "aliases": aliases
                    }
                    
                    commands_dict[command_name] = command_info
                    
                    # 为别名也建立索引
                    for alias in aliases:
                        if not alias.startswith("/"):
                            alias = "/" + alias
                        commands_dict[alias] = {
                            **command_info,
                            "command": alias,
                            "is_alias_of": command_name
                        }
        
        self._command_cache = commands_dict
        logger.info(f"已缓存 {len(commands_dict)} 个指令（含别名）")
        return commands_dict

    def _search_similar_commands(self, keyword: str, limit: int = 5) -> List[Dict]:
        """
        搜索相似的指令
        支持模糊匹配、拼音匹配等
        """
        all_commands = self._get_all_commands()
        keyword_lower = keyword.lower().strip()
        
        # 移除开头的 /
        if keyword_lower.startswith("/"):
            keyword_lower = keyword_lower[1:]
        
        results = []
        
        # 1. 精确匹配
        exact_match = f"/{keyword_lower}"
        if exact_match in all_commands:
            results.append(all_commands[exact_match])
        
        # 2. 模糊匹配 - 命令名包含关键词
        for cmd_name, cmd_info in all_commands.items():
            if cmd_info in results:
                continue
            
            cmd_name_lower = cmd_name.lower()
            if keyword_lower in cmd_name_lower:
                results.append(cmd_info)
        
        # 3. 描述匹配 - 描述包含关键词
        if len(results) < limit:
            for cmd_info in all_commands.values():
                if cmd_info in results:
                    continue
                
                desc_lower = cmd_info["description"].lower()
                if keyword_lower in desc_lower:
                    results.append(cmd_info)
                
                if len(results) >= limit:
                    break
        
        # 4. 插件名匹配
        if len(results) < limit:
            for cmd_info in all_commands.values():
                if cmd_info in results:
                    continue
                
                plugin_lower = cmd_info["plugin"].lower()
                if keyword_lower in plugin_lower:
                    results.append(cmd_info)
                
                if len(results) >= limit:
                    break
        
        return results[:limit]

    @filter.llm_tool(name="search_command")
    async def search_command(self, event: AstrMessageEvent, **kwargs) -> str:
        """🔍 模糊搜索指令 - 当用户输错指令或询问功能时使用
        
        ⚠️ 重要使用时机：
        1. 用户输入了不存在的指令（如 "/钩鱼"、"/抽将"）→ 立即调用此函数纠正
        2. 用户询问某个功能是否存在（如 "有抽奖吗"、"能不能钓鱼"）→ 调用此函数查找
        3. 用户描述想要的功能但不知道指令名（如 "我想玩游戏"）→ 调用此函数搜索
        4. 用户记不清完整指令名（如 "那个钓什么来着"）→ 调用此函数查找
        
        Args:
            keyword(string): 搜索关键词，可以是错误的指令名（如 "钩鱼"）、功能描述词（如 "抽奖"、"游戏"）、插件名的一部分（如 "钓鱼"）
        
        返回:
            JSON 格式，包含最多 5 条匹配的指令信息
        
        使用示例:
            用户说："/钩鱼" → 调用 search_command(keyword="钩鱼") → 找到 "/钓鱼"
            用户说："有抽奖功能吗" → 调用 search_command(keyword="抽奖") → 找到相关指令
        """
        try:
            keyword = kwargs.get('keyword', '')
            if not keyword:
                return json.dumps({
                    "success": False,
                    "message": "缺少必需参数: keyword",
                    "results": []
                }, ensure_ascii=False, indent=2)
            
            logger.info(f"LLM搜索指令: {keyword}")
            
            results = self._search_similar_commands(keyword, limit=5)
            
            if not results:
                return json.dumps({
                    "success": False,
                    "message": f"未找到与 '{keyword}' 相关的指令",
                    "results": []
                }, ensure_ascii=False, indent=2)
            
            # 清理结果，移除内部字段，并替换前缀
            clean_results = []
            for result in results:
                clean_result = {
                    "command": self._replace_prefix(result["command"]),
                    "description": result["description"],
                    "plugin": result["plugin"],
                    "aliases": [self._replace_prefix(alias) for alias in result["aliases"]]
                }
                if "is_alias_of" in result:
                    clean_result["is_alias_of"] = self._replace_prefix(result["is_alias_of"])
                clean_results.append(clean_result)
            
            logger.info(f"找到 {len(clean_results)} 条相关指令")
            return json.dumps({
                "success": True,
                "message": f"找到 {len(clean_results)} 条与 '{keyword}' 相关的指令",
                "results": clean_results
            }, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"搜索指令时发生错误: {e}")
            return json.dumps({
                "success": False,
                "message": f"搜索失败: {str(e)}",
                "results": []
            }, ensure_ascii=False, indent=2)

    @filter.llm_tool(name="get_command_detail")
    async def get_command_detail(self, event: AstrMessageEvent, **kwargs) -> str:
        """📖 获取指令详细信息 - 当用户询问"怎么用"时调用
        
        ⚠️ 重要使用时机：
        1. 用户明确询问某个指令的用法（如 "钓鱼指令怎么用"、"/抽奖是干什么的"）→ 立即调用
        2. 用户提到某个指令但不知道参数（如 "钓鱼指令需要什么参数"）→ 调用此函数
        3. 用户想了解指令的详细说明（如 "详细说说钓鱼功能"）→ 调用此函数
        4. 已通过 search_command 找到指令，用户想深入了解 → 继续调用此函数获取详情
        
        Args:
            command_name(string): 指令名，可以带或不带 / 前缀（会自动补全）
        
        返回:
            JSON 格式，包含指令的完整信息和相关推荐
        
        使用示例:
            用户说："钓鱼指令怎么用" → 调用 get_command_detail(command_name="钓鱼")
            用户说："/抽奖 是什么" → 调用 get_command_detail(command_name="/抽奖")
        """
        try:
            command_name = kwargs.get('command_name', '')
            if not command_name:
                return json.dumps({
                    "success": False,
                    "message": "缺少必需参数: command_name"
                }, ensure_ascii=False, indent=2)
            
            logger.info(f"LLM查询指令详情: {command_name}")
            
            # 标准化指令名
            if not command_name.startswith("/"):
                command_name = "/" + command_name
            
            all_commands = self._get_all_commands()
            
            # 查找指令
            if command_name not in all_commands:
                # 尝试搜索相似指令
                similar = self._search_similar_commands(command_name, limit=3)
                return json.dumps({
                    "success": False,
                    "message": f"未找到指令 '{command_name}'",
                    "suggestions": [cmd["command"] for cmd in similar]
                }, ensure_ascii=False, indent=2)
            
            cmd_info = all_commands[command_name]
            
            # 查找同插件的其他指令（相关推荐）
            plugin_name = cmd_info["plugin"]
            similar_commands = []
            for cmd_name, cmd_data in all_commands.items():
                if cmd_data["plugin"] == plugin_name and cmd_name != command_name:
                    # 跳过别名
                    if "is_alias_of" not in cmd_data:
                        similar_commands.append(cmd_name)
                        if len(similar_commands) >= 3:
                            break
            
            result = {
                "success": True,
                "command": self._replace_prefix(cmd_info["command"]),
                "description": cmd_info["description"],
                "plugin": cmd_info["plugin"],
                "aliases": [self._replace_prefix(alias) for alias in cmd_info["aliases"]],
                "similar_commands": [self._replace_prefix(cmd) for cmd in similar_commands]
            }
            
            if "is_alias_of" in cmd_info:
                result["is_alias_of"] = self._replace_prefix(cmd_info["is_alias_of"])
                result["note"] = f"这是 {self._replace_prefix(cmd_info['is_alias_of'])} 的别名"
            
            logger.info(f"成功获取指令详情: {command_name}")
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"查询指令详情时发生错误: {e}")
            return json.dumps({
                "success": False,
                "message": f"查询失败: {str(e)}"
            }, ensure_ascii=False, indent=2)

    @filter.llm_tool(name="list_plugin_commands")
    async def list_plugin_commands(self, event: AstrMessageEvent, **kwargs) -> str:
        """📦 列出插件功能 - 查看所有插件或某个插件的指令列表
        
        ⚠️ 重要使用时机：
        
        【不传 plugin_name 参数 = 列出所有插件】👈 最常用！
        1. 用户询问"有哪些插件"、"有什么功能"、"能做什么" → 不传参数，列出所有插件
        2. 用户想浏览系统功能（如 "给我介绍下有啥"）→ 不传参数
        3. 用户问"一共多少个插件" → 不传参数
        
        【传入 plugin_name 参数 = 查看某个插件的所有指令】
        4. 用户询问某个插件有什么功能（如 "钓鱼插件有什么玩法"）→ 传入插件名
        5. 用户想深入了解某个插件（如 "抽奖插件都有哪些指令"）→ 传入插件名
        
        Args:
            plugin_name(string): 【可选参数，默认为空】
                                - 不传或传空字符串 → 返回所有插件名称列表 ⭐ 重点！
                                - 传入插件名 → 返回该插件的所有指令
        
        返回:
            JSON 格式，根据参数返回不同内容
        
        使用示例:
            用户说："有哪些插件" → 调用 list_plugin_commands()
            用户说："钓鱼插件有什么" → 调用 list_plugin_commands(plugin_name="钓鱼")
        """
        try:
            plugin_name = kwargs.get('plugin_name', '')
            logger.info(f"LLM查询插件指令: {plugin_name or '所有插件'}")
            
            all_commands = self._get_all_commands()
            
            # 按插件分组
            plugins_dict = collections.defaultdict(list)
            for cmd_info in all_commands.values():
                # 跳过别名
                if "is_alias_of" not in cmd_info:
                    plugins_dict[cmd_info["plugin"]].append(cmd_info)
            
            # 如果没有指定插件名，返回所有插件列表
            if not plugin_name:
                plugin_list = sorted(plugins_dict.keys())
                return json.dumps({
                    "success": True,
                    "message": f"系统共有 {len(plugin_list)} 个插件",
                    "plugins": plugin_list,
                    "hint": "使用 list_plugin_commands 并指定 plugin_name 参数查看具体插件的指令"
                }, ensure_ascii=False, indent=2)
            
            # 搜索匹配的插件（支持模糊匹配）
            plugin_name_lower = plugin_name.lower()
            matched_plugin = None
            for pname in plugins_dict.keys():
                if plugin_name_lower in pname.lower():
                    matched_plugin = pname
                    break
            
            if not matched_plugin:
                return json.dumps({
                    "success": False,
                    "message": f"未找到插件 '{plugin_name}'",
                    "available_plugins": sorted(plugins_dict.keys())
                }, ensure_ascii=False, indent=2)
            
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
                        "aliases": [self._replace_prefix(alias) for alias in cmd["aliases"]]
                    }
                    for cmd in commands
                ]
            }
            
            logger.info(f"找到插件 '{matched_plugin}' 的 {len(commands)} 条指令")
            return json.dumps(result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"查询插件指令时发生错误: {e}")
            return json.dumps({
                "success": False,
                "message": f"查询失败: {str(e)}"
            }, ensure_ascii=False, indent=2)

    @filter.command("测试指令搜索", alias={"test_search"})
    async def test_search(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        """测试指令：搜索指令功能"""
        # 从消息中提取关键词
        message = event.message_str.replace("/测试指令搜索", "").replace("/test_search", "").strip()
        
        if not message:
            yield event.plain_result("用法: /测试指令搜索 <关键词>\n例如: /测试指令搜索 钓鱼")
            return
        
        logger.info(f"测试搜索指令: {message}")
        result_str = await self.search_command(event, message)
        
        try:
            result_data = json.loads(result_str)
            
            if not result_data.get("success"):
                yield event.plain_result(f"❌ {result_data.get('message', '搜索失败')}")
                return
            
            results = result_data.get("results", [])
            if not results:
                yield event.plain_result(f"未找到与 '{message}' 相关的指令")
                return
            
            result_text = f"🔍 搜索 '{message}' 的结果：\n\n"
            for i, cmd in enumerate(results, 1):
                result_text += f"{i}. {cmd['command']}\n"
                result_text += f"   📦 插件: {cmd['plugin']}\n"
                result_text += f"   📝 描述: {cmd['description']}\n"
                if cmd.get('aliases'):
                    result_text += f"   🔗 别名: {', '.join(cmd['aliases'])}\n"
                if cmd.get('is_alias_of'):
                    result_text += f"   ℹ️  这是 {cmd['is_alias_of']} 的别名\n"
                result_text += "\n"
            
            yield event.plain_result(result_text.strip())
            
        except json.JSONDecodeError:
            yield event.plain_result(f"数据解析失败：\n{result_str}")

    @filter.command("测试指令详情", alias={"test_detail"})
    async def test_detail(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        """测试指令：查询指令详情"""
        message = event.message_str.replace("/测试指令详情", "").replace("/test_detail", "").strip()
        
        if not message:
            yield event.plain_result("用法: /测试指令详情 <指令名>\n例如: /测试指令详情 钓鱼")
            return
        
        logger.info(f"测试查询指令详情: {message}")
        result_str = await self.get_command_detail(event, message)
        
        try:
            result_data = json.loads(result_str)
            
            if not result_data.get("success"):
                msg = result_data.get('message', '查询失败')
                suggestions = result_data.get('suggestions', [])
                result_text = f"❌ {msg}\n"
                if suggestions:
                    result_text += f"\n💡 你可能想找：\n"
                    for cmd in suggestions:
                        result_text += f"  • {cmd}\n"
                yield event.plain_result(result_text.strip())
                return
            
            result_text = f"📋 指令详情\n\n"
            result_text += f"🎯 指令: {result_data['command']}\n"
            result_text += f"📦 插件: {result_data['plugin']}\n"
            result_text += f"📝 描述: {result_data['description']}\n"
            
            if result_data.get('aliases'):
                result_text += f"🔗 别名: {', '.join(result_data['aliases'])}\n"
            
            if result_data.get('is_alias_of'):
                result_text += f"\nℹ️  {result_data.get('note', '')}\n"
            
            if result_data.get('similar_commands'):
                result_text += f"\n💡 相关指令:\n"
                for cmd in result_data['similar_commands']:
                    result_text += f"  • {cmd}\n"
            
            yield event.plain_result(result_text.strip())
            
        except json.JSONDecodeError:
            yield event.plain_result(f"数据解析失败：\n{result_str}")

    @filter.command("测试插件列表", alias={"test_plugins"})
    async def test_plugins(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        """测试指令：查看插件列表或插件的指令"""
        message = event.message_str.replace("/测试插件列表", "").replace("/test_plugins", "").strip()
        
        logger.info(f"测试查询插件: {message or '所有插件'}")
        result_str = await self.list_plugin_commands(event, message)
        
        try:
            result_data = json.loads(result_str)
            
            if not result_data.get("success"):
                msg = result_data.get('message', '查询失败')
                result_text = f"❌ {msg}\n"
                
                available = result_data.get('available_plugins', [])
                if available:
                    result_text += f"\n可用插件列表：\n"
                    for plugin in available[:10]:
                        result_text += f"  • {plugin}\n"
                    if len(available) > 10:
                        result_text += f"  ... 还有 {len(available) - 10} 个插件\n"
                
                yield event.plain_result(result_text.strip())
                return
            
            # 如果是插件列表
            if "plugins" in result_data:
                plugins = result_data["plugins"]
                result_text = f"📦 系统插件列表 ({len(plugins)} 个)\n\n"
                for plugin in plugins[:20]:
                    result_text += f"  • {plugin}\n"
                if len(plugins) > 20:
                    result_text += f"\n... 还有 {len(plugins) - 20} 个插件\n"
                result_text += f"\n💡 使用 /测试插件列表 <插件名> 查看插件的指令"
                yield event.plain_result(result_text.strip())
                return
            
            # 如果是插件的指令列表
            plugin = result_data.get("plugin", "")
            commands = result_data.get("commands", [])
            
            result_text = f"📦 {plugin}\n"
            result_text += f"共 {len(commands)} 条指令\n\n"
            
            for cmd in commands:
                result_text += f"• {cmd['command']}\n"
                result_text += f"  {cmd['description']}\n"
                if cmd.get('aliases'):
                    result_text += f"  别名: {', '.join(cmd['aliases'])}\n"
                result_text += "\n"
            
            yield event.plain_result(result_text.strip())
            
        except json.JSONDecodeError:
            yield event.plain_result(f"数据解析失败：\n{result_str}")

    @filter.command("指令查询帮助", alias={"query_help"})
    async def help_command(self, event: AstrMessageEvent) -> AsyncGenerator[MessageEventResult, None]:
        """显示插件帮助信息"""
        help_text = """=== 指令查询插件 v2.0 ===
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

【测试命令】
/测试指令搜索 <关键词>  - 测试搜索功能
/测试指令详情 <指令名>  - 测试详情查询
/测试插件列表 [插件名]  - 测试插件查询
/指令查询帮助         - 显示本帮助

【设计理念】
精简实用，只返回必要信息
支持模糊匹配，智能推荐
让 LLM 成为用户的指令助手"""
        
        yield event.plain_result(help_text)

    async def terminate(self) -> None:
        """插件卸载时调用"""
        logger.info("指令查询插件已卸载")
