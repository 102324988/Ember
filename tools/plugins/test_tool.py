"""
测试工具

用于验证插件自动发现功能
"""

import logging
from tools.base import BaseTool, ToolResult, ToolPermission

logger = logging.getLogger(__name__)


class TestTool(BaseTool):
    """
    测试工具 - 验证插件系统是否正常工作
    """

    name = "test_tool"
    description = (
        "一个简单的测试工具，用于验证插件自动发现功能是否正常工作（不允许调用）"
    )
    short_description = "测试工具，验证插件系统（不允许调用）"
    permission = ToolPermission.READONLY
    timeout = 5.0
    version = "1.0.0"

    examples = [
        {
            "scenario": "测试插件系统",
            "parameters": {"message": "hello"},
        }
    ]

    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "测试消息",
            },
        },
        "required": ["message"],
    }

    def execute(self, params: dict) -> ToolResult:
        """
        执行测试工具
        """
        message = params.get("message", "")
        logger.info(f"[TestTool] 收到消息: {message}")

        return ToolResult.ok(
            data={
                "echo": message,
                "status": "插件系统工作正常！",
            }
        )

    def summarize_result(self, result: ToolResult, max_length: int = 200) -> str:
        if not result.success:
            return f"测试失败: {result.error}"
        return f"测试成功: {result.data.get('status', 'OK')}"
