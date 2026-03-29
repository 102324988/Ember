"""
导入器基类
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """导入结果"""

    success: bool
    message: str = ""
    data: Any = None
    error: Optional[str] = None
    stats: dict = None

    def __post_init__(self):
        if self.stats is None:
            self.stats = {}


class BaseImporter(ABC):
    """
    导入器基类

    所有导入器必须继承此类并实现 import_data 方法。
    """

    name: str = "base"
    description: str = "基础导入器"

    def __init__(self, source_dir: str):
        """
        初始化导入器

        Args:
            source_dir: 源目录路径 (解压后的存档目录)
        """
        self.source_dir = source_dir
        self.logger = logging.getLogger(f"importer.{self.name}")

    @abstractmethod
    def import_data(self) -> ImportResult:
        """
        执行导入操作

        Returns:
            ImportResult 导入结果
        """
        pass

    def pre_import(self) -> bool:
        """
        导入前准备

        Returns:
            是否准备成功
        """
        return True

    def post_import(self) -> None:
        """导入后清理"""
        pass

    def run(self) -> ImportResult:
        """
        运行完整的导入流程

        Returns:
            ImportResult 导入结果
        """
        try:
            if not self.pre_import():
                return ImportResult(
                    success=False,
                    error=f"{self.name}: 导入前准备失败",
                )

            result = self.import_data()

            self.post_import()

            if result.success:
                self.logger.info(f"{self.name} 导入成功: {result.message}")
            else:
                self.logger.error(f"{self.name} 导入失败: {result.error}")

            return result

        except Exception as e:
            self.logger.error(f"{self.name} 导入异常: {e}")
            return ImportResult(success=False, error=str(e))
