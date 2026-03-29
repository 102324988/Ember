"""
工具基类和类型定义

提供工具接口系统的基础抽象类、枚举类型和数据类。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
from enum import Enum, auto
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class ToolPermission(Enum):
    """工具权限级别"""
    READONLY = auto()    # 只读工具，只能获取信息
    READWRITE = auto()   # 读写工具，可以修改状态或创建内容
    DESTRUCTIVE = auto() # 破坏性工具，可以删除数据（需谨慎）


class ToolError(Exception):
    """工具执行错误基类"""
    pass


class ToolTimeoutError(ToolError):
    """工具执行超时错误"""
    pass


class ToolPermissionError(ToolError):
    """工具权限错误"""
    pass


class ToolValidationError(ToolError):
    """工具参数验证错误"""
    pass


@dataclass
class ToolResult:
    """
    工具执行结果

    Attributes:
        success: 是否成功执行
        data: 成功时的返回数据
        error: 失败时的错误信息
        metadata: 额外的元数据（执行时间、日志等）
    """
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, data: Any = None, **metadata) -> "ToolResult":
        """创建成功结果"""
        return cls(success=True, data=data, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata) -> "ToolResult":
        """创建失败结果"""
        return cls(success=False, error=error, metadata=metadata)


class BaseTool(ABC):
    """
    工具基类

    所有工具必须继承此类并实现 execute 方法。

    Attributes:
        name: 工具唯一标识名（snake_case）
        description: 工具功能描述（用于LLM理解）
        short_description: 精简描述（20字以内，用于prompt）
        parameters: JSON Schema 格式的参数定义
        permission: 工具权限级别
        timeout: 默认超时时间（秒）
        version: 语义化版本号
        deprecated: 是否已弃用
        examples: 使用示例列表
    """

    name: str = ""
    description: str = ""
    short_description: str = ""  # 精简描述（20字以内，用于prompt）
    parameters: dict = None  # 在__init__中初始化，避免可变默认值问题
    permission: ToolPermission = ToolPermission.READONLY
    timeout: float = 30.0
    version: str = "1.0.0"  # 语义化版本
    deprecated: bool = False  # 是否已弃用
    examples: list = None  # 在__init__中初始化，避免可变默认值问题

    def __init__(self):
        """初始化工具，子类可覆盖添加额外设置"""
        if not self.name:
            raise ValueError(f"{self.__class__.__name__} 必须设置 name 属性")
        if not self.description:
            raise ValueError(f"{self.__class__.__name__} 必须设置 description 属性")

        # 初始化可变默认值（避免类属性共享）
        if self.parameters is None:
            self.parameters = {
                "type": "object",
                "properties": {},
            }
        if self.examples is None:
            self.examples = []

        # 确保 parameters 符合 JSON Schema 基本结构
        if not self.parameters:
            self.parameters = {
                "type": "object",
                "properties": {},
            }
        if "type" not in self.parameters:
            self.parameters["type"] = "object"

    @abstractmethod
    def execute(self, params: dict) -> ToolResult:
        """
        执行工具

        Args:
            params: 经过验证的参数字典

        Returns:
            ToolResult: 执行结果
        """
        pass

    def validate_params(self, params: dict) -> tuple[bool, Optional[str]]:
        """
        验证参数是否符合 schema

        Args:
            params: 待验证的参数

        Returns:
            (是否有效, 错误信息)
        """
        # 基础验证：检查必需参数
        required = self.parameters.get("required", [])
        for param in required:
            if param not in params:
                return False, f"缺少必需参数: {param}"

        # 检查参数类型
        properties = self.parameters.get("properties", {})
        for key, value in params.items():
            if key in properties:
                expected_type = properties[key].get("type")
                if expected_type and not self._check_type(value, expected_type):
                    return False, f"参数 {key} 类型错误，期望 {expected_type}"

        return True, None

    def _check_type(self, value: Any, expected_type: str) -> bool:
        """检查值是否符合期望类型"""
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }

        if expected_type == "null":
            return value is None

        python_type = type_map.get(expected_type)
        if python_type is None:
            return True  # 未知类型，放行

        return isinstance(value, python_type)

    def get_schema(self) -> dict:
        """
        获取工具的 JSON Schema 描述（用于LLM function calling）

        Returns:
            符合 OpenAI Function Calling 格式的工具描述
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def get_tool_description_for_prompt(self) -> str:
        """
        获取工具描述文本（用于直接注入 prompt）

        Returns:
            工具使用的文本说明
        """
        lines = [f"- {self.name}: {self.description}"]

        properties = self.parameters.get("properties", {})
        if properties:
            lines.append("  参数:")
            for param_name, param_info in properties.items():
                param_desc = param_info.get("description", "无描述")
                param_type = param_info.get("type", "any")
                required_mark = " (必需)" if param_name in self.parameters.get("required", []) else ""
                lines.append(f"    - {param_name} ({param_type}){required_mark}: {param_desc}")

        return "\n".join(lines)

    def get_compact_prompt_description(self) -> str:
        """
        获取精简的工具描述（用于LLM prompt，节省token）

        只展示关键信息：名称、简短描述、必需参数名
        参数schema细节不在prompt中展示，仅用于验证

        Returns:
            精简的工具描述文本（约30-50 token）
        """
        desc = self.short_description or self.description[:30]
        required = self.parameters.get("required", [])
        req_str = f" 必需:{','.join(required)}" if required else ""
        deprecated_mark = " [已弃用]" if self.deprecated else ""

        return f"- {self.name}: {desc}{req_str}{deprecated_mark}"

    def get_examples_text(self) -> str:
        """
        获取工具使用示例的文本格式

        Returns:
            示例文本，用于引导LLM正确使用工具
        """
        if not self.examples:
            return ""

        lines = [f"  示例:"]
        for ex in self.examples[:2]:  # 最多展示2个示例
            user_msg = ex.get("user", "")
            params = ex.get("parameters", {})
            params_json = json.dumps(params, ensure_ascii=False)
            lines.append(f'    用户: {user_msg}')
            lines.append(f'    调用: <tool>{{"name": "{self.name}", "parameters": {params_json}}}</tool>')

        return "\n".join(lines)

    def summarize_result(self, result: ToolResult, max_length: int = 200) -> str:
        """
        将工具结果摘要为自然语言（供LLM阅读）

        子类可覆盖此方法，提供领域特定的摘要逻辑

        Args:
            result: 工具执行结果
            max_length: 摘要最大长度

        Returns:
            自然语言摘要
        """
        if not result.success:
            return f"执行失败: {result.error}"

        if result.data is None:
            return "执行成功"

        # 简单摘要策略
        if isinstance(result.data, str):
            text = result.data
        elif isinstance(result.data, (int, float, bool)):
            text = str(result.data)
        elif isinstance(result.data, dict):
            # 提取关键字段
            key_fields = []
            for k, v in result.data.items():
                if k in ('message', 'content', 'text', 'summary', 'result'):
                    if isinstance(v, str):
                        key_fields.append(v)
                        break
                elif k in ('data', 'items', 'list'):
                    if isinstance(v, list):
                        key_fields.append(f"{len(v)}条数据")
            text = " | ".join(key_fields) if key_fields else str(result.data)
        elif isinstance(result.data, list):
            text = f"{len(result.data)}条数据"
        else:
            text = str(result.data)

        # 截断
        if len(text) > max_length:
            text = text[:max_length - 3] + "..."

        return text

    def get_full_identifier(self) -> str:
        """返回带版本的完整标识"""
        return f"{self.name}@v{self.version}"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', permission={self.permission.name})>"
