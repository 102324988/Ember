"""
测试工具执行器

覆盖 ToolExecutor 的执行、权限控制、超时处理功能。
"""
import time
import pytest
from unittest.mock import Mock
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from tools.base import BaseTool, ToolResult, ToolPermission


class SlowTool(BaseTool):
    """模拟慢速工具"""
    name = "slow_tool"
    description = "A slow tool"
    parameters = {"type": "object", "properties": {}}
    permission = ToolPermission.READONLY
    timeout = 1.0

    def execute(self, params: dict) -> ToolResult:
        time.sleep(2)  # 比 timeout 长
        return ToolResult.ok()


class ErrorTool(BaseTool):
    """模拟错误工具"""
    name = "error_tool"
    description = "A tool that raises error"
    parameters = {"type": "object", "properties": {}}
    permission = ToolPermission.READONLY

    def execute(self, params: dict) -> ToolResult:
        raise ValueError("Intentional error")


class ReadOnlyTool(BaseTool):
    name = "readonly_tool"
    description = "A readonly tool"
    parameters = {"type": "object", "properties": {}}
    permission = ToolPermission.READONLY

    def execute(self, params: dict) -> ToolResult:
        return ToolResult.ok(data="readonly_result")


class WriteTool(BaseTool):
    name = "write_tool"
    description = "A write tool"
    parameters = {"type": "object", "properties": {}}
    permission = ToolPermission.READWRITE

    def execute(self, params: dict) -> ToolResult:
        return ToolResult.ok()


class DestructiveTool(BaseTool):
    name = "destructive_tool"
    description = "A destructive tool"
    parameters = {"type": "object", "properties": {}}
    permission = ToolPermission.DESTRUCTIVE

    def execute(self, params: dict) -> ToolResult:
        return ToolResult.ok()


class ValidationTool(BaseTool):
    name = "validation_tool"
    description = "A tool with required params"
    parameters = {
        "type": "object",
        "properties": {
            "required_param": {"type": "string"},
            "optional_param": {"type": "integer"},
        },
        "required": ["required_param"],
    }
    permission = ToolPermission.READONLY

    def execute(self, params: dict) -> ToolResult:
        return ToolResult.ok(data=params.get("required_param"))


class TestToolExecutor:
    """测试工具执行器"""

    @pytest.fixture
    def registry(self):
        reg = ToolRegistry()
        reg.register(ReadOnlyTool())
        reg.register(WriteTool())
        reg.register(DestructiveTool())
        return reg

    @pytest.fixture
    def executor(self, registry):
        return ToolExecutor(registry, max_permission=ToolPermission.READWRITE)

    def test_execute_success(self, executor):
        """测试成功执行"""
        result = executor.execute("readonly_tool", {})
        assert result.success is True
        assert result.data == "readonly_result"

    def test_execute_nonexistent_tool(self, executor):
        """测试执行不存在的工具"""
        result = executor.execute("nonexistent", {})
        assert result.success is False
        assert "未注册" in result.error

    def test_execute_validation_error(self, registry):
        """测试参数验证失败"""
        registry.register(ValidationTool())
        executor = ToolExecutor(registry)
        result = executor.execute("validation_tool", {})
        assert result.success is False
        assert "参数验证失败" in result.error

    def test_execute_permission_denied_readwrite(self, executor):
        """测试读写权限拒绝"""
        # executor 默认权限是 READWRITE
        result = executor.execute("destructive_tool", {})
        assert result.success is False
        assert "权限不足" in result.error

    def test_execute_permission_allowed_readonly(self, registry):
        """测试只读权限允许"""
        executor = ToolExecutor(registry, max_permission=ToolPermission.READWRITE)
        result = executor.execute("readonly_tool", {})
        assert result.success is True

    def test_can_execute(self, executor):
        """测试权限检查"""
        assert executor.can_execute("readonly_tool") is True
        assert executor.can_execute("write_tool") is True
        assert executor.can_execute("destructive_tool") is False
        assert executor.can_execute("nonexistent") is False

    def test_execute_timeout(self):
        """测试超时处理"""
        reg = ToolRegistry()
        reg.register(SlowTool())
        executor = ToolExecutor(reg, default_timeout=0.5)

        result = executor.execute("slow_tool", {})
        assert result.success is False
        assert "超时" in result.error

    def test_execute_exception_handling(self):
        """测试异常处理"""
        reg = ToolRegistry()
        reg.register(ErrorTool())
        executor = ToolExecutor(reg)

        result = executor.execute("error_tool", {})
        assert result.success is False
        assert "执行异常" in result.error

    def test_get_stats(self, executor):
        """测试获取统计信息"""
        executor.execute("readonly_tool", {})
        executor.execute("readonly_tool", {})
        executor.execute("destructive_tool", {})  # 失败

        stats = executor.get_stats()
        assert stats["total_calls"] == 3
        assert stats["success_calls"] == 2
        assert stats["failed_calls"] == 1

    def test_reset_stats(self, executor):
        """测试重置统计"""
        executor.execute("readonly_tool", {})
        executor.reset_stats()

        stats = executor.get_stats()
        assert stats["total_calls"] == 0

    def test_pre_execute_hook(self, executor):
        """测试执行前钩子"""
        hook_called = []

        def hook(tool_name, params):
            hook_called.append((tool_name, params))

        executor.add_pre_execute_hook(hook)
        executor.execute("readonly_tool", {"test": "value"})

        assert len(hook_called) == 1
        assert hook_called[0] == ("readonly_tool", {"test": "value"})

    def test_post_execute_hook(self, executor):
        """测试执行后钩子"""
        hook_called = []

        def hook(tool_name, params, result):
            hook_called.append((tool_name, result.success))

        executor.add_post_execute_hook(hook)
        executor.execute("readonly_tool", {})

        assert len(hook_called) == 1
        assert hook_called[0][1] is True  # success=True

    def test_hook_exception_handling(self, executor):
        """测试钩子异常不影响主流程"""
        def bad_hook(*args):
            raise ValueError("Hook error")

        executor.add_pre_execute_hook(bad_hook)
        # 不应该抛出异常
        result = executor.execute("readonly_tool", {})
        assert result.success is True

    def test_context_manager(self, registry):
        """测试上下文管理器"""
        with ToolExecutor(registry) as executor:
            result = executor.execute("readonly_tool", {})
            assert result.success is True

    def test_execution_time_metadata(self, executor):
        """测试执行时间元数据"""
        result = executor.execute("readonly_tool", {})
        assert "execution_time" in result.metadata
        assert result.metadata["execution_time"] >= 0

    def test_tool_specific_timeout_override(self, registry):
        """测试工具特定超时覆盖"""
        reg = ToolRegistry()
        reg.register(SlowTool())
        executor = ToolExecutor(reg)

        # SlowTool.timeout = 1.0，但我们给更长的超时
        result = executor.execute("slow_tool", {}, timeout=3.0)
        assert result.success is True
