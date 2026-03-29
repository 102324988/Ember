"""
Ember 可拓展工具接口系统

提供AI角色与外部世界交互的能力：
- 工具基类定义
- 工具注册与执行
- 工具调用处理器
- 插件化工具扩展
"""

from tools.base import (
    BaseTool,
    ToolResult,
    ToolPermission,
    ToolError,
    ToolTimeoutError,
    ToolPermissionError,
    ToolValidationError,
)
from tools.registry import ToolRegistry
from tools.executor import ToolExecutor
from tools.processor import ToolCallProcessor
from tools.plugin import (
    ToolPluginManager,
    get_plugin_manager,
    auto_discover_tools,
    create_tool_template,
)
from tools.builtin import MemoryQueryTool

__all__ = [
    # 基础类
    "BaseTool",
    "ToolResult",
    "ToolPermission",
    "ToolError",
    "ToolTimeoutError",
    "ToolPermissionError",
    "ToolValidationError",
    # 核心组件
    "ToolRegistry",
    "ToolExecutor",
    "ToolCallProcessor",
    "ToolEnabledBrain",
    # 插件系统
    "ToolPluginManager",
    "get_plugin_manager",
    "auto_discover_tools",
    "create_tool_template",
    # 内置工具
    "MemoryQueryTool",
]
