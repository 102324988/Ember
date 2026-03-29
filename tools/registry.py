"""
工具注册中心

提供工具注册、发现、和元数据管理功能。
生成LLM可用的工具描述JSON。
"""

import logging
from typing import Dict, List, Optional, Type
from tools.base import BaseTool, ToolPermission

logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    工具注册中心

    管理所有可用工具的注册和发现，为 LLM 提供工具描述。

    Example:
        >>> registry = ToolRegistry()
        >>> registry.register(TimeTool())
        >>> registry.register(FileTool())
        >>> schemas = registry.get_all_schemas()
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._permission_filter: Optional[ToolPermission] = None

    def register(self, tool: BaseTool, overwrite: bool = False) -> bool:
        """
        注册工具

        Args:
            tool: 工具实例
            overwrite: 是否覆盖已存在的同名工具

        Returns:
            是否注册成功
        """
        name = tool.name

        if name in self._tools and not overwrite:
            logger.warning(
                f"工具 '{name}' 已存在，跳过注册（使用 overwrite=True 覆盖）"
            )
            return False

        self._tools[name] = tool
        logger.debug(f"注册工具: {name} ({tool.permission.name})")
        return True

    def unregister(self, name: str) -> bool:
        """
        注销工具

        Args:
            name: 工具名称

        Returns:
            是否成功注销
        """
        if name not in self._tools:
            logger.warning(f"工具 '{name}' 不存在，无法注销")
            return False

        del self._tools[name]
        logger.debug(f"注销工具: {name}")
        return True

    def get(self, name: str) -> Optional[BaseTool]:
        """
        获取工具实例

        Args:
            name: 工具名称

        Returns:
            工具实例，不存在则返回 None
        """
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """
        检查工具是否已注册

        Args:
            name: 工具名称

        Returns:
            是否已注册
        """
        return name in self._tools

    def list_tools(self, permission: Optional[ToolPermission] = None) -> List[str]:
        """
        列出所有已注册工具名称

        Args:
            permission: 按权限级别过滤，None 表示不过滤

        Returns:
            工具名称列表
        """
        if permission is None:
            return list(self._tools.keys())

        return [
            name for name, tool in self._tools.items() if tool.permission == permission
        ]

    def get_all_schemas(self) -> List[dict]:
        """
        获取所有工具的 JSON Schema 描述

        Returns:
            符合 OpenAI Function Calling 格式的工具描述列表
        """
        return [tool.get_schema() for tool in self._tools.values()]

    def get_schema(self, name: str) -> Optional[dict]:
        """
        获取单个工具的 JSON Schema 描述

        Args:
            name: 工具名称

        Returns:
            工具描述，不存在则返回 None
        """
        tool = self._tools.get(name)
        return tool.get_schema() if tool else None

    def get_tools_description_for_prompt(
        self,
        permission: Optional[ToolPermission] = None,
        compact: bool = True,
        include_examples: bool = True,
        tool_names: Optional[List[str]] = None,
    ) -> str:
        """
        生成工具使用说明文本（用于注入 System Prompt）

        Args:
            permission: 按权限级别过滤，None 表示不过滤
            compact: 是否使用精简描述（节省token）
            include_examples: 是否包含使用示例
            tool_names: 指定要包含的工具列表，None表示全部

        Returns:
            工具说明文本
        """
        tools = self._tools.values()
        if permission is not None:
            tools = [t for t in tools if t.permission == permission]
        if tool_names is not None:
            tools = [t for t in tools if t.name in tool_names]

        if not tools:
            return ""

        lines = ["【可用工具】"]

        for tool in tools:
            if compact:
                lines.append(tool.get_compact_prompt_description())
            else:
                lines.append(tool.get_tool_description_for_prompt())

        if include_examples:
            lines.append("")
            lines.append("【使用示例】")
            for tool in tools:
                ex_text = tool.get_examples_text()
                if ex_text:
                    lines.append(ex_text)

            # 通用格式说明
            lines.append("")
            lines.append("【格式规范】")
            lines.append(
                '- 工具调用: <tool>{"name": "工具名", "parameters": {...}}</tool>'
            )
            lines.append("- 参数必须符合工具要求")
            lines.append(
                '- 请直接在 <tool> 标签内输出 JSON 对象，严禁使用 <arg_value> 或任何其他嵌套标签。输出格式必须严格遵守：<tool>{"name":...}</tool>，不要在中间插入任何额外字符。'
            )
            lines.append(
                "- 注意，如果当前对话的上下文不足以让你生成自然的回答，你应该优先使用工具来获取信息或进行操作，而不是直接回复"
            )
            lines.append("- 请在一次对话内调用完所有的工具，最多可以调用5个工具")
            lines.append("- 调用工具的信息需要单独发送")
            lines.append(
                "- 如果你检测到对话历史中已有工具调用，你必须立刻根据工具结果生成回复，【绝对禁止】再次调用任何工具。"
            )
            lines.append(
                "- 请确保<tool></tool>的工具调用紧接在<thought>之后，以便于筛除。"
            )

        return "\n".join(lines)

    def clear(self):
        """清空所有注册的工具"""
        count = len(self._tools)
        self._tools.clear()
        logger.debug(f"清空 {count} 个工具")

    def register_from_class(self, tool_class: Type[BaseTool], *args, **kwargs) -> bool:
        """
        从工具类自动实例化并注册

        Args:
            tool_class: 工具类
            *args, **kwargs: 传递给工具构造函数的参数

        Returns:
            是否注册成功
        """
        try:
            tool = tool_class(*args, **kwargs)
            return self.register(tool)
        except Exception as e:
            logger.error(f"实例化工具 {tool_class.__name__} 失败: {e}")
            return False

    def get_stats(self) -> dict:
        """
        获取注册中心统计信息

        Returns:
            统计信息字典
        """
        total = len(self._tools)
        by_permission = {
            "READONLY": len(self.list_tools(ToolPermission.READONLY)),
            "READWRITE": len(self.list_tools(ToolPermission.READWRITE)),
            "DESTRUCTIVE": len(self.list_tools(ToolPermission.DESTRUCTIVE)),
        }

        return {
            "total": total,
            "by_permission": by_permission,
            "tools": self.list_tools(),
        }

    def __len__(self) -> int:
        """返回已注册工具数量"""
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """检查是否包含指定工具"""
        return name in self._tools

    def __iter__(self):
        """迭代所有工具"""
        return iter(self._tools.values())
