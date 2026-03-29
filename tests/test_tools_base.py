"""
测试工具基类

覆盖 BaseTool、ToolResult 和权限系统的核心功能。
"""
import pytest
from tools.base import (
    BaseTool,
    ToolResult,
    ToolPermission,
    ToolError,
    ToolTimeoutError,
    ToolPermissionError,
    ToolValidationError,
)


class MockTool(BaseTool):
    """测试用的模拟工具"""
    name = "mock_tool"
    description = "A mock tool for testing"
    parameters = {
        "type": "object",
        "properties": {
            "value": {"type": "string", "description": "Input value"},
            "count": {"type": "integer", "description": "Count value"},
        },
        "required": ["value"],
    }
    permission = ToolPermission.READONLY

    def execute(self, params: dict) -> ToolResult:
        return ToolResult.ok(data={"received": params.get("value")})


class TestToolResult:
    """测试 ToolResult 数据类"""

    def test_ok_factory_method(self):
        """测试成功结果工厂方法"""
        result = ToolResult.ok(data="test_data", extra="info")
        assert result.success is True
        assert result.data == "test_data"
        assert result.error is None
        assert result.metadata["extra"] == "info"

    def test_fail_factory_method(self):
        """测试失败结果工厂方法"""
        result = ToolResult.fail("something went wrong", code=500)
        assert result.success is False
        assert result.error == "something went wrong"
        assert result.data is None
        assert result.metadata["code"] == 500

    def test_default_metadata(self):
        """测试默认元数据"""
        result = ToolResult(success=True)
        assert result.metadata == {}


class TestBaseTool:
    """测试 BaseTool 抽象类"""

    def test_tool_initialization(self):
        """测试工具初始化"""
        tool = MockTool()
        assert tool.name == "mock_tool"
        assert tool.permission == ToolPermission.READONLY

    def test_tool_missing_name_raises(self):
        """测试缺少 name 属性时抛出异常"""
        class BadTool(BaseTool):
            description = "bad tool"

            def execute(self, params: dict) -> ToolResult:
                return ToolResult.ok()

        with pytest.raises(ValueError, match="必须设置 name 属性"):
            BadTool()

    def test_tool_missing_description_raises(self):
        """测试缺少 description 属性时抛出异常"""
        class BadTool(BaseTool):
            name = "bad_tool"

            def execute(self, params: dict) -> ToolResult:
                return ToolResult.ok()

        with pytest.raises(ValueError, match="必须设置 description 属性"):
            BadTool()

    def test_validate_params_success(self):
        """测试参数验证成功"""
        tool = MockTool()
        valid, error = tool.validate_params({"value": "test", "count": 5})
        assert valid is True
        assert error is None

    def test_validate_params_missing_required(self):
        """测试缺少必需参数"""
        tool = MockTool()
        valid, error = tool.validate_params({"count": 5})
        assert valid is False
        assert "缺少必需参数" in error
        assert "value" in error

    def test_validate_params_wrong_type(self):
        """测试参数类型错误"""
        tool = MockTool()
        valid, error = tool.validate_params({"value": "test", "count": "not_a_number"})
        assert valid is False
        assert "类型错误" in error

    def test_get_schema(self):
        """测试获取 JSON Schema"""
        tool = MockTool()
        schema = tool.get_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "mock_tool"
        assert "parameters" in schema["function"]

    def test_get_tool_description_for_prompt(self):
        """测试获取工具描述文本"""
        tool = MockTool()
        desc = tool.get_tool_description_for_prompt()
        assert "mock_tool" in desc
        assert "value" in desc
        assert "(必需)" in desc  # value is required


class TestToolPermission:
    """测试权限枚举"""

    def test_permission_values(self):
        """测试权限值定义"""
        assert ToolPermission.READONLY.name == "READONLY"
        assert ToolPermission.READWRITE.name == "READWRITE"
        assert ToolPermission.DESTRUCTIVE.name == "DESTRUCTIVE"

    def test_permission_comparison(self):
        """测试权限级别比较（按定义顺序）"""
        # 枚举自动赋值，按定义顺序
        readonly_val = ToolPermission.READONLY.value
        readwrite_val = ToolPermission.READWRITE.value
        destructive_val = ToolPermission.DESTRUCTIVE.value

        assert readonly_val < readwrite_val < destructive_val


class TestToolErrors:
    """测试工具异常类"""

    def test_tool_error_inheritance(self):
        """测试异常继承关系"""
        assert issubclass(ToolTimeoutError, ToolError)
        assert issubclass(ToolPermissionError, ToolError)
        assert issubclass(ToolValidationError, ToolError)

    def test_error_can_be_caught(self):
        """测试异常可以被捕获"""
        try:
            raise ToolTimeoutError("timeout")
        except ToolError as e:
            assert "timeout" in str(e)
