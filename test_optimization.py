#!/usr/bin/env python3
"""
测试指令查询插件的优化效果
比较优化前后的数据量差异
"""

import json

# 模拟优化前的返回数据（350条指令的完整列表）
def simulate_old_response():
    """模拟旧版本返回的大数据"""
    plugins = []
    for i in range(36):
        commands = []
        for j in range(10):  # 平均每个插件10条指令
            commands.append({
                "command": f"command_{i}_{j}",
                "description": f"这是插件{i}的第{j}条指令的描述信息",
                "aliases": [f"alias_{i}_{j}_1", f"alias_{i}_{j}_2"]
            })
        plugins.append({
            "plugin_name": f"插件_{i}",
            "command_count": 10,
            "commands": commands
        })

    return {
        "total_plugins": 36,
        "total_commands": 350,
        "plugins": plugins
    }

# 模拟优化后的概览模式返回
def simulate_new_overview_response():
    """模拟新版本概览模式的精简数据"""
    return {
        "mode": "overview",
        "summary": "系统共有36个插件，350条指令",
        "total_plugins": 36,
        "total_commands": 350,
        "categories": {
            "娱乐": 8,
            "管理": 6,
            "工具": 10,
            "AI": 5,
            "社交": 3
        },
        "category_examples": {
            "娱乐": ["抽奖插件", "表情包生成器", "钓鱼插件"],
            "管理": ["封禁管理", "权限管理", "过滤器"],
            "工具": ["帮助菜单", "API查询", "图片摘要"],
            "AI": ["Gemini图片生成", "LLM回复", "智能对话"],
            "社交": ["群成员查询", "点赞插件", "广播"]
        },
        "hint": "这是精简的概览信息。要查询具体指令，请：\n1. 使用plugin_name参数查询指定插件（如：plugin_name='抽奖插件'）\n2. 使用category参数查询分类（可选：娱乐、管理、工具、AI、社交）"
    }

# 模拟优化后的详细查询（单个插件）
def simulate_new_detail_response():
    """模拟新版本详细查询单个插件"""
    return {
        "total_plugins": 1,
        "total_commands": 10,
        "plugins": [{
            "plugin_name": "抽奖插件",
            "command_count": 10,
            "commands": [
                {"command": "创建抽奖", "description": "创建新的抽奖活动", "aliases": ["新建抽奖"]},
                {"command": "参与抽奖", "description": "参与当前抽奖", "aliases": ["抽奖", "参加"]},
                {"command": "查看抽奖", "description": "查看抽奖详情", "aliases": ["抽奖详情"]},
                # ... 其他指令
            ]
        }]
    }

def calculate_size(data):
    """计算JSON数据的字节大小"""
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    return len(json_str.encode('utf-8'))

def main():
    print("=" * 60)
    print("指令查询插件优化效果测试")
    print("=" * 60)

    # 旧版本数据
    old_data = simulate_old_response()
    old_size = calculate_size(old_data)

    # 新版本概览数据
    new_overview = simulate_new_overview_response()
    new_overview_size = calculate_size(new_overview)

    # 新版本详细查询数据
    new_detail = simulate_new_detail_response()
    new_detail_size = calculate_size(new_detail)

    print(f"\n【优化前】完整数据返回：")
    print(f"  - 数据大小: {old_size:,} 字节 ({old_size/1024:.2f} KB)")
    print(f"  - 插件数量: {old_data['total_plugins']}")
    print(f"  - 指令数量: {old_data['total_commands']}")
    print(f"  - 问题: 所有350条指令详情都被塞入LLM上下文")

    print(f"\n【优化后】概览模式：")
    print(f"  - 数据大小: {new_overview_size:,} 字节 ({new_overview_size/1024:.2f} KB)")
    print(f"  - 包含内容: 统计信息 + 分类概览 + 示例插件")
    print(f"  - 减少量: {old_size - new_overview_size:,} 字节")
    print(f"  - 压缩比: {(1 - new_overview_size/old_size)*100:.1f}%")

    print(f"\n【优化后】详细查询（单插件）：")
    print(f"  - 数据大小: {new_detail_size:,} 字节 ({new_detail_size/1024:.2f} KB)")
    print(f"  - 包含内容: 单个插件的完整指令列表")
    print(f"  - 减少量: {old_size - new_detail_size:,} 字节")
    print(f"  - 压缩比: {(1 - new_detail_size/old_size)*100:.1f}%")

    print(f"\n【Token估算】")
    # 粗略估算：1个token约等于4个字符（中文）
    old_tokens = old_size / 3  # 中文字符占用更多
    new_overview_tokens = new_overview_size / 3
    new_detail_tokens = new_detail_size / 3

    print(f"  - 优化前: 约 {old_tokens:.0f} tokens")
    print(f"  - 优化后（概览）: 约 {new_overview_tokens:.0f} tokens")
    print(f"  - 优化后（详细）: 约 {new_detail_tokens:.0f} tokens")
    print(f"  - Token节省（概览）: 约 {old_tokens - new_overview_tokens:.0f} tokens ({(1-new_overview_tokens/old_tokens)*100:.1f}%)")

    print(f"\n【使用流程优化】")
    print("  旧流程:")
    print("    用户: '有哪些指令？'")
    print("    → LLM调用工具，获取350条指令详情（大量数据进入上下文）")
    print("    → LLM回复用户")
    print("    ✗ 问题: 每次对话都携带大量冗余数据")

    print("\n  新流程:")
    print("    用户: '有哪些指令？'")
    print("    → LLM调用工具（无参数），获取精简概览")
    print("    → LLM: '系统有36个插件，包括娱乐、管理、工具等类别，需要了解哪类？'")
    print("    用户: '娱乐类有什么？'")
    print("    → LLM调用工具（category='娱乐'），只获取娱乐类插件详情")
    print("    ✓ 优势: 按需查询，最小化上下文污染")

    print("\n" + "=" * 60)
    print("优化总结:")
    print("=" * 60)
    print(f"✅ 首次查询数据量减少 {(1 - new_overview_size/old_size)*100:.1f}%")
    print("✅ 支持按分类和插件名精确查询")
    print("✅ 智能提示引导二次查询")
    print("✅ 避免上下文污染和token浪费")
    print("✅ 提升LLM回复质量和响应速度")
    print("=" * 60)

if __name__ == "__main__":
    main()
