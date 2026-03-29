"""
工具执行器

提供统一的工具调用入口，包含权限控制、超时处理、错误处理和日志记录。
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Optional, Callable
from tools.base import (
    BaseTool,
    ToolResult,
    ToolPermission,
    ToolPermissionError,
    ToolTimeoutError,
    ToolValidationError,
)
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    工具执行器

    统一处理工具调用，提供权限控制、超时管理和错误处理。

    Example:
        >>> executor = ToolExecutor(registry)
        >>> result = executor.execute("time_tool", {"format": "iso"})
        >>> if result.success:
        ...     print(f"时间: {result.data}")
    """

    def __init__(
        self,
        registry: ToolRegistry,
        max_permission: ToolPermission = ToolPermission.READWRITE,
        default_timeout: float = 30.0,
        max_workers: int = 4,
    ):
        """
        初始化执行器

        Args:
            registry: 工具注册中心
            max_permission: 最大允许的权限级别
            default_timeout: 默认超时时间（秒）
            max_workers: 线程池最大工作线程数
        """
        self.registry = registry
        self.max_permission = max_permission
        self.default_timeout = default_timeout
        self._thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self._pre_execute_hooks: list[Callable[[str, dict], None]] = []
        self._post_execute_hooks: list[Callable[[str, dict, ToolResult], None]] = []

        # 调用统计
        self._stats = {
            "total_calls": 0,
            "success_calls": 0,
            "failed_calls": 0,
            "tool_stats": {},  # {tool_name: {"calls": 0, "errors": 0, "total_time": 0}}
        }

    def execute(
        self,
        tool_name: str,
        params: dict,
        timeout: Optional[float] = None,
        skip_permission_check: bool = False,
    ) -> ToolResult:
        """
        执行工具

        Args:
            tool_name: 工具名称
            params: 工具参数
            timeout: 超时时间（秒），None 使用默认值
            skip_permission_check: 是否跳过权限检查（仅内部使用）

        Returns:
            ToolResult: 执行结果
        """
        start_time = time.time()
        self._stats["total_calls"] += 1

        # 记录工具统计
        if tool_name not in self._stats["tool_stats"]:
            self._stats["tool_stats"][tool_name] = {
                "calls": 0,
                "errors": 0,
                "total_time": 0.0,
            }
        self._stats["tool_stats"][tool_name]["calls"] += 1

        # 1. 查找工具
        tool = self.registry.get(tool_name)
        if tool is None:
            error_msg = f"工具 '{tool_name}' 未注册"
            logger.warning(error_msg)
            self._stats["failed_calls"] += 1
            self._stats["tool_stats"][tool_name]["errors"] += 1
            return ToolResult.fail(error_msg, tool_name=tool_name)

        # 2. 权限检查
        if not skip_permission_check and not self._check_permission(tool):
            error_msg = f"权限不足，无法执行 '{tool_name}'（需要 {tool.permission.name}，当前最大 {self.max_permission.name}）"
            logger.warning(error_msg)
            self._stats["failed_calls"] += 1
            self._stats["tool_stats"][tool_name]["errors"] += 1
            return ToolResult.fail(error_msg, permission_denied=True)

        # 3. 参数验证
        valid, error = tool.validate_params(params)
        if not valid:
            error_msg = f"参数验证失败: {error}"
            logger.warning(f"[{tool_name}] {error_msg}")
            self._stats["failed_calls"] += 1
            self._stats["tool_stats"][tool_name]["errors"] += 1
            return ToolResult.fail(error_msg, validation_error=True)

        # 4. 执行前钩子
        for hook in self._pre_execute_hooks:
            try:
                hook(tool_name, params)
            except Exception as e:
                logger.warning(f"执行前钩子失败: {e}")

        # 5. 执行工具（带超时）
        actual_timeout = timeout or tool.timeout or self.default_timeout
        result = self._execute_with_timeout(tool, params, actual_timeout)

        # 6. 记录执行时间
        elapsed = time.time() - start_time
        self._stats["tool_stats"][tool_name]["total_time"] += elapsed

        # 7. 更新统计
        if result.success:
            self._stats["success_calls"] += 1
            logger.info(f"[{tool_name}] 执行成功 ({elapsed:.3f}s)")
        else:
            self._stats["failed_calls"] += 1
            self._stats["tool_stats"][tool_name]["errors"] += 1
            logger.warning(f"[{tool_name}] 执行失败: {result.error}")

        # 8. 执行后钩子
        for hook in self._post_execute_hooks:
            try:
                hook(tool_name, params, result)
            except Exception as e:
                logger.warning(f"执行后钩子失败: {e}")

        # 添加执行元数据
        result.metadata["execution_time"] = elapsed
        result.metadata["tool_name"] = tool_name

        return result

    def _execute_with_timeout(
        self, tool: BaseTool, params: dict, timeout: float
    ) -> ToolResult:
        """在线程池中执行工具并设置超时"""
        try:
            future = self._thread_pool.submit(tool.execute, params)
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            error_msg = f"工具 '{tool.name}' 执行超时（>{timeout}s）"
            logger.error(error_msg)
            return ToolResult.fail(error_msg, timeout=True)
        except Exception as e:
            error_msg = f"工具执行异常: {type(e).__name__}: {str(e)}"
            logger.exception(f"[{tool.name}] 执行异常")
            return ToolResult.fail(error_msg, exception_type=type(e).__name__)

    def _check_permission(self, tool: BaseTool) -> bool:
        """检查工具权限是否在允许范围内"""
        permission_levels = {
            ToolPermission.READONLY: 0,
            ToolPermission.READWRITE: 1,
            ToolPermission.DESTRUCTIVE: 2,
        }
        tool_level = permission_levels.get(tool.permission, 0)
        max_level = permission_levels.get(self.max_permission, 1)
        return tool_level <= max_level

    def can_execute(self, tool_name: str) -> bool:
        """
        检查是否可以执行指定工具

        Args:
            tool_name: 工具名称

        Returns:
            是否有权限执行
        """
        tool = self.registry.get(tool_name)
        if tool is None:
            return False
        return self._check_permission(tool)

    def add_pre_execute_hook(self, hook: Callable[[str, dict], None]):
        """添加执行前钩子"""
        self._pre_execute_hooks.append(hook)

    def add_post_execute_hook(self, hook: Callable[[str, dict, ToolResult], None]):
        """添加执行后钩子"""
        self._post_execute_hooks.append(hook)

    def get_stats(self) -> dict:
        """
        获取执行统计信息

        Returns:
            统计信息字典
        """
        stats = self._stats.copy()
        # 计算平均执行时间
        for tool_name, tool_stat in stats["tool_stats"].items():
            calls = tool_stat["calls"]
            if calls > 0:
                tool_stat["avg_time"] = tool_stat["total_time"] / calls
                tool_stat["success_rate"] = (calls - tool_stat["errors"]) / calls
        return stats

    def reset_stats(self):
        """重置统计信息"""
        self._stats = {
            "total_calls": 0,
            "success_calls": 0,
            "failed_calls": 0,
            "tool_stats": {},
        }

    def shutdown(self):
        """关闭执行器，清理资源"""
        self._thread_pool.shutdown(wait=True)
        logger.info("ToolExecutor 已关闭")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
