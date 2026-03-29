"""
测试工具注册中心

覆盖 ToolRegistry 的注册、发现、查询功能。
"""
import pytest
from tools.registry import ToolRegistry
from tools.base import BaseTool, ToolResult, ToolPermission


class SampleTool(BaseTool):
    name = "test_tool"
    description = "A test tool"
    parameters = {"type": "object", "properties": {}}
    permission = ToolPermission.READONLY

    def execute(self, params: dict) -> ToolResult:
        return ToolResult.ok()


class WriteTool(BaseTool):
    name = "write_tool"
    description = "A write tool"
    parameters = {"type": "object", "properties": {}}
    permission = ToolPermission.READWRITE

    def execute(self, params: dict) -> ToolResult:
        return ToolResult.ok()


class DeleteTool(BaseTool):
    name = "delete_tool"
    description = "A delete tool"
    parameters = {"type": "object", "properties": {}}
    permission = ToolPermission.DESTRUCTIVE

    def execute(self, params: dict) -> ToolResult:
        return ToolResult.ok()


class ToolRegistryTests:
    """测试工具注册中心"""

    @pytest.fixture
    def registry(self):
        """创建空的注册中心"""
        return ToolRegistry()

    @pytest.fixture
    def populated_registry(self):
        """创建已填充的注册中心"""
        reg = ToolRegistry()
        reg.register(SampleTool())
        reg.register(WriteTool())
        return reg

    def test_register_tool(self, registry):
        """测试注册工具"""
        tool = SampleTool()
        result = registry.register(tool)
        assert result is True
        assert registry.has("test_tool")

    def test_register_duplicate_without_overwrite(self, registry):
        """测试重复注册（不覆盖）"""
        registry.register(SampleTool())
        result = registry.register(SampleTool())
        assert result is False  # 不覆盖，返回False

    def test_register_duplicate_with_overwrite(self, registry):
        """测试重复注册（覆盖）"""
        registry.register(SampleTool())
        result = registry.register(SampleTool(), overwrite=True)
        assert result is True  # 覆盖成功

    def test_unregister_tool(self, registry):
        """测试注销工具"""
        registry.register(SampleTool())
        result = registry.unregister("test_tool")
        assert result is True
        assert not registry.has("test_tool")

    def test_unregister_nonexistent(self, registry):
        """测试注销不存在的工具"""
        result = registry.unregister("nonexistent")
        assert result is False

    def test_get_tool(self, populated_registry):
        """测试获取工具"""
        tool = populated_registry.get("test_tool")
        assert tool is not None
        assert tool.name == "test_tool"

    def test_get_nonexistent(self, registry):
        """测试获取不存在的工具"""
        tool = registry.get("nonexistent")
        assert tool is None

    def test_list_tools(self, populated_registry):
        """测试列出所有工具"""
        tools = populated_registry.list_tools()
        assert "test_tool" in tools
        assert "write_tool" in tools

    def test_list_tools_by_permission(self, populated_registry):
        """测试按权限过滤列出工具"""
        readonly_tools = populated_registry.list_tools(ToolPermission.READONLY)
        assert "test_tool" in readonly_tools
        assert "write_tool" not in readonly_tools

        readwrite_tools = populated_registry.list_tools(ToolPermission.READWRITE)
        assert "write_tool" in readwrite_tools
        assert "test_tool" not in readwrite_tools

    def test_get_all_schemas(self, populated_registry):
        """测试获取所有工具schema"""
        schemas = populated_registry.get_all_schemas()
        assert len(schemas) == 2
        names = [s["function"]["name"] for s in schemas]
        assert "test_tool" in names
        assert "write_tool" in names

    def test_get_single_schema(self, populated_registry):
        """测试获取单个工具schema"""
        schema = populated_registry.get_schema("test_tool")
        assert schema is not None
        assert schema["function"]["name"] == "test_tool"

    def test_get_schema_nonexistent(self, registry):
        """测试获取不存在工具的schema"""
        schema = registry.get_schema("nonexistent")
        assert schema is None

    def test_clear_registry(self, populated_registry):
        """测试清空注册中心"""
        populated_registry.clear()
        assert len(populated_registry) == 0

    def test_get_stats(self, populated_registry):
        """测试获取统计信息"""
        stats = populated_registry.get_stats()
        assert stats["total"] == 2
        assert stats["by_permission"]["READONLY"] == 1
        assert stats["by_permission"]["READWRITE"] == 1

    def test_len_method(self, populated_registry):
        """测试 __len__ 方法"""
        assert len(populated_registry) == 2

    def test_contains_operator(self, populated_registry):
        """测试 __contains__ 操作符"""
        assert "test_tool" in populated_registry
        assert "nonexistent" not in populated_registry

    def test_iteration(self, populated_registry):
        """测试迭代"""
        tools = list(populated_registry)
        assert len(tools) == 2
        names = [t.name for t in tools]
        assert "test_tool" in names
        assert "write_tool" in names

    def test_register_from_class(self, registry):
        """测试从类注册工具"""
        result = registry.register_from_class(SampleTool)
        assert result is True
        assert "test_tool" in registry

    def test_register_from_class_failure(self, registry):
        """测试从类注册失败的情况"""
        class BadTool(BaseTool):
            # 缺少 name 和 description
            def execute(self, params):
                return None

        result = registry.register_from_class(BadTool)
        assert result is False

    def test_get_tools_description_for_prompt(self, populated_registry):
        """测试生成工具描述文本"""
        desc = populated_registry.get_tools_description_for_prompt()
        assert "test_tool" in desc
        assert "write_tool" in desc
        assert "你可以使用以下工具" in desc

    def test_get_tools_description_empty(self, registry):
        """测试空注册中心的描述"""
        desc = registry.get_tools_description_for_prompt()
        assert desc == ""
