"""
工具插件管理器

支持从指定目录自动加载工具，简化工具添加流程。
实现插件化架构，工具定义在单一文件，自动注册。
"""

import importlib
import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import List, Type, Optional, Dict, Any
from dataclasses import dataclass, field

from tools.base import BaseTool

logger = logging.getLogger(__name__)


@dataclass
class PluginMetadata:
    """插件元数据"""

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


class ToolPluginManager:
    """
    工具插件管理器

    支持从指定目录自动发现并加载工具类。
    简化工具添加流程：只需在 plugins 目录创建工具文件即可。

    Example:
        >>> manager = ToolPluginManager()
        >>> tools = manager.discover_tools()
        >>> for tool_class in tools:
        ...     registry.register(tool_class())

        >>> # 加载特定插件目录
        >>> manager = ToolPluginManager(plugin_dir="custom_plugins")
        >>> manager.load_all_plugins(registry)
    """

    # 默认插件目录
    DEFAULT_PLUGIN_DIR = "tools/plugins"

    # 工具类文件命名模式
    TOOL_FILE_PATTERN = "*_tool.py"

    def __init__(self, plugin_dir: Optional[str] = None):
        """
        初始化插件管理器

        Args:
            plugin_dir: 插件目录路径，None则使用默认目录
        """
        self.plugin_dir = Path(plugin_dir or self.DEFAULT_PLUGIN_DIR)
        self._loaded_plugins: Dict[str, Any] = {}
        self._tool_classes: Dict[str, Type[BaseTool]] = {}

    def discover_tools(self) -> List[Type[BaseTool]]:
        """
        自动发现并加载所有工具类

        扫描插件目录，查找所有继承自 BaseTool 的类。

        Returns:
            发现的工具类列表
        """
        tools = []

        if not self.plugin_dir.exists():
            logger.debug(f"插件目录不存在: {self.plugin_dir}")
            return tools

        for py_file in self.plugin_dir.glob(self.TOOL_FILE_PATTERN):
            try:
                module_tools = self._load_tools_from_file(py_file)
                tools.extend(module_tools)
                logger.debug(f"从 {py_file.name} 发现 {len(module_tools)} 个工具")
            except Exception as e:
                logger.warning(f"加载工具文件 {py_file} 失败: {e}")

        return tools

    def _load_tools_from_file(self, py_file: Path) -> List[Type[BaseTool]]:
        """
        从单个 Python 文件加载工具类（使用 importlib.util 避免 sys.path 污染）

        Args:
            py_file: Python 文件路径

        Returns:
            BaseTool 子类列表
        """
        tools = []

        # 构建模块名（使用扁平命名避免父包依赖问题）
        module_name = f"tools_plugins_{py_file.stem}"

        try:
            # 如果模块已加载，直接使用缓存的工具类
            if module_name in self._loaded_plugins:
                # 返回已缓存的工具类（避免重复加载）
                cached_tool_names = [
                    name
                    for name, cls in self._tool_classes.items()
                    if cls.__module__ == module_name
                ]
                for name in cached_tool_names:
                    tools.append(self._tool_classes[name])
                return tools

            # 从文件路径加载新模块
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"无法加载模块: {py_file}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module  # 注册到 sys.modules 以便相对导入
            try:
                spec.loader.exec_module(module)
            except Exception:
                # 加载失败时清理 sys.modules
                sys.modules.pop(module_name, None)
                raise

            # 查找 BaseTool 子类
            for name, obj in inspect.getmembers(module):
                if (
                    inspect.isclass(obj)
                    and issubclass(obj, BaseTool)
                    and obj is not BaseTool
                    and hasattr(obj, "name")
                    and obj.name  # 确保 name 已设置
                ):
                    tools.append(obj)
                    self._tool_classes[obj.name] = obj

            self._loaded_plugins[module_name] = module

        except Exception as e:
            logger.error(f"导入模块 {module_name} 失败: {e}")
            raise

        return tools

    def load_all_plugins(self, registry) -> int:
        """
        加载所有插件并注册到注册中心

        Args:
            registry: ToolRegistry 实例

        Returns:
            成功加载的工具数量
        """
        tool_classes = self.discover_tools()
        count = 0

        for tool_class in tool_classes:
            try:
                tool = tool_class()
                if registry.register(tool):
                    count += 1
                    logger.info(f"自动注册工具: {tool.name}")
            except Exception as e:
                logger.error(f"实例化工具 {tool_class.__name__} 失败: {e}")

        return count

    def get_tool_class(self, name: str) -> Optional[Type[BaseTool]]:
        """
        获取已加载的工具类

        Args:
            name: 工具名称

        Returns:
            工具类或 None
        """
        return self._tool_classes.get(name)

    def reload_plugin(self, tool_name: str) -> bool:
        """
        热重载指定工具

        Args:
            tool_name: 工具名称

        Returns:
            是否成功重载
        """
        tool_class = self._tool_classes.get(tool_name)
        if not tool_class:
            logger.warning(f"工具 {tool_name} 未加载，无法重载")
            return False

        module_name = tool_class.__module__
        if module_name in sys.modules:
            try:
                importlib.reload(sys.modules[module_name])
                logger.info(f"热重载模块: {module_name}")
                return True
            except Exception as e:
                logger.error(f"热重载失败: {e}")
                return False

        return False

    def list_loaded_plugins(self) -> List[str]:
        """
        列出已加载的插件模块

        Returns:
            模块名列表
        """
        return list(self._loaded_plugins.keys())

    def list_discovered_tools(self) -> List[str]:
        """
        列出已发现的工具

        Returns:
            工具名称列表
        """
        return list(self._tool_classes.keys())

    def get_plugin_info(self) -> Dict[str, Any]:
        """
        获取插件系统信息

        Returns:
            信息字典
        """
        return {
            "plugin_dir": str(self.plugin_dir),
            "plugin_dir_exists": self.plugin_dir.exists(),
            "loaded_modules": len(self._loaded_plugins),
            "discovered_tools": list(self._tool_classes.keys()),
        }


# 全局插件管理器实例
_default_manager: Optional[ToolPluginManager] = None


def get_plugin_manager(plugin_dir: Optional[str] = None) -> ToolPluginManager:
    """
    获取默认的插件管理器实例

    Args:
        plugin_dir: 可选的插件目录覆盖

    Returns:
        ToolPluginManager 实例
    """
    global _default_manager
    if _default_manager is None or plugin_dir:
        _default_manager = ToolPluginManager(plugin_dir)
    return _default_manager


def auto_discover_tools(registry, plugin_dir: Optional[str] = None) -> int:
    """
    自动发现并注册所有工具（便捷函数）

    Args:
        registry: ToolRegistry 实例
        plugin_dir: 可选的插件目录

    Returns:
        成功注册的工具数量

    Example:
        >>> from tools.registry import ToolRegistry
        >>> registry = ToolRegistry()
        >>> count = auto_discover_tools(registry)
        >>> print(f"自动注册了 {count} 个工具")
    """
    manager = get_plugin_manager(plugin_dir)
    return manager.load_all_plugins(registry)


def create_tool_template(tool_name: str, output_dir: Optional[str] = None) -> Path:
    """
    创建新工具模板文件

    Args:
        tool_name: 工具名称（snake_case）
        output_dir: 输出目录，None则使用默认插件目录

    Returns:
        创建的模板文件路径

    Example:
        >>> path = create_tool_template("weather_tool")
        >>> print(f"模板已创建: {path}")
    """
    target_dir = Path(output_dir or ToolPluginManager.DEFAULT_PLUGIN_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)

    # 确保文件名符合 *_tool.py 模式
    if not tool_name.endswith("_tool"):
        tool_name = f"{tool_name}_tool"
    file_path = target_dir / f"{tool_name}.py"

    template = f'''"""
{tool_name} 工具

工具功能描述
"""
import logging
from tools.base import BaseTool, ToolResult, ToolPermission

logger = logging.getLogger(__name__)


class {tool_name.replace("_", " ").title().replace(" ", "")}(BaseTool):
    """
    工具描述
    """

    name = "{tool_name}"
    description = "工具功能描述（用于LLM理解）"
    short_description = "精简描述（20字以内）"
    permission = ToolPermission.READONLY
    timeout = 10.0
    version = "1.0.0"

    # 使用示例
    examples = [
        {{
            "user": "用户输入示例",
            "parameters": {{"param1": "value1"}}
        }}
    ]

    parameters = {{
        "type": "object",
        "properties": {{
            "param1": {{
                "type": "string",
                "description": "参数描述",
            }},
        }},
        "required": ["param1"],
    }}

    def execute(self, params: dict) -> ToolResult:
        """
        执行工具

        Args:
            params: 参数字典

        Returns:
            ToolResult: 执行结果
        """
        try:
            param1 = params.get("param1", "")

            # 实现工具逻辑
            result = f"处理结果: {{param1}}"

            return ToolResult.ok(data=result)

        except Exception as e:
            logger.exception("{tool_name} 执行失败")
            return ToolResult.fail(f"执行失败: {{str(e)}}")

    def summarize_result(self, result: ToolResult, max_length: int = 200) -> str:
        """
        结果摘要（可选，自定义摘要逻辑）
        """
        if not result.success:
            return f"失败: {{result.error}}"
        # 自定义摘要逻辑
        return str(result.data)[:max_length]
'''

    file_path.write_text(template, encoding="utf-8")
    logger.info(f"工具模板已创建: {file_path}")
    return file_path
