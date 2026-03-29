"""
导出器基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExportResult:
    """导出结果"""

    success: bool
    data: Any = None
    file_path: str = ""
    error: Optional[str] = None
    stats: dict = None

    def __post_init__(self):
        if self.stats is None:
            self.stats = {}


class BaseExporter(ABC):
    """
    导出器基类

    所有导出器必须继承此类并实现 export 方法。
    """

    name: str = "base"
    description: str = "基础导出器"

    def __init__(self, output_dir: str):
        """
        初始化导出器

        Args:
            output_dir: 输出目录路径
        """
        self.output_dir = output_dir
        self.logger = logging.getLogger(f"exporter.{self.name}")

    @abstractmethod
    def export(self) -> ExportResult:
        """
        执行导出操作

        Returns:
            ExportResult 导出结果
        """
        pass

    def pre_export(self) -> bool:
        """
        导出前准备

        Returns:
            是否准备成功
        """
        return True

    def post_export(self) -> None:
        """导出后清理"""
        pass

    def run(self) -> ExportResult:
        """
        运行完整的导出流程

        Returns:
            ExportResult 导出结果
        """
        try:
            if not self.pre_export():
                return ExportResult(
                    success=False,
                    error=f"{self.name}: 导出前准备失败",
                )

            result = self.export()

            self.post_export()

            if result.success:
                self.logger.info(f"{self.name} 导出成功")
            else:
                self.logger.error(f"{self.name} 导出失败: {result.error}")

            return result

        except Exception as e:
            self.logger.error(f"{self.name} 导出异常: {e}")
            return ExportResult(success=False, error=str(e))
