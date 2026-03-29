"""
存档数据模型定义
"""

from dataclasses import dataclass, field, asdict
from typing import Optional, List
from datetime import datetime
import json


@dataclass
class ArchiveStats:
    """存档统计信息"""

    message_count: int = 0
    memory_count: int = 0
    entity_count: int = 0
    relation_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ArchiveStats":
        return cls(
            message_count=data.get("message_count", 0),
            memory_count=data.get("memory_count", 0),
            entity_count=data.get("entity_count", 0),
            relation_count=data.get("relation_count", 0),
        )


@dataclass
class ArchiveManifest:
    """
    存档元数据清单

    每个存档都包含一个 manifest.json 文件，记录存档的基本信息。
    """

    # 存档格式版本
    version: str = "1.0"

    # 创建时间 (ISO 格式)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # 角色名称
    character_name: str = "依鸣"

    # 游戏内逻辑时间
    logical_time: str = ""

    # 存档描述
    description: str = ""

    # 统计信息
    stats: ArchiveStats = field(default_factory=ArchiveStats)

    # 文件校验和 (用于完整性验证)
    checksum: str = ""

    # 存档来源版本 (代码版本)
    source_version: str = ""

    # 额外元数据
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "character_name": self.character_name,
            "logical_time": self.logical_time,
            "description": self.description,
            "stats": self.stats.to_dict(),
            "checksum": self.checksum,
            "source_version": self.source_version,
            "extra": self.extra,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "ArchiveManifest":
        stats_data = data.get("stats", {})
        if isinstance(stats_data, dict):
            stats = ArchiveStats.from_dict(stats_data)
        else:
            stats = ArchiveStats()

        return cls(
            version=data.get("version", "1.0"),
            created_at=data.get("created_at", ""),
            character_name=data.get("character_name", "依鸣"),
            logical_time=data.get("logical_time", ""),
            description=data.get("description", ""),
            stats=stats,
            checksum=data.get("checksum", ""),
            source_version=data.get("source_version", ""),
            extra=data.get("extra", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "ArchiveManifest":
        data = json.loads(json_str)
        return cls.from_dict(data)


@dataclass
class ArchiveSlot:
    """
    存档槽信息

    用于存档列表展示，不包含实际数据。
    """

    # 存档槽名称 (文件名，不含扩展名)
    slot_name: str

    # 显示名称
    display_name: str

    # 创建时间
    created_at: str

    # 游戏内时间
    logical_time: str

    # 描述
    description: str

    # 存档文件路径
    file_path: str

    # 文件大小 (字节)
    file_size: int = 0

    # 是否有效
    is_valid: bool = True

    # 错误信息 (如果无效)
    error_message: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ArchiveSlot":
        return cls(
            slot_name=data.get("slot_name", ""),
            display_name=data.get("display_name", ""),
            created_at=data.get("created_at", ""),
            logical_time=data.get("logical_time", ""),
            description=data.get("description", ""),
            file_path=data.get("file_path", ""),
            file_size=data.get("file_size", 0),
            is_valid=data.get("is_valid", True),
            error_message=data.get("error_message", ""),
        )


@dataclass
class ArchiveResult:
    """存档操作结果"""

    success: bool
    message: str
    slot_name: str = ""
    manifest: Optional[ArchiveManifest] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        result = {
            "success": self.success,
            "message": self.message,
            "slot_name": self.slot_name,
        }
        if self.manifest:
            result["manifest"] = self.manifest.to_dict()
        if self.error:
            result["error"] = self.error
        return result
