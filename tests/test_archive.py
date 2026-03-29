"""
存档系统测试
"""

import pytest
import os
import json
import tempfile
import shutil
from pathlib import Path

# 添加项目根目录到路径
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from archive import ArchiveManager, ArchiveManifest, ArchiveStats
from archive.exceptions import ArchiveNotFoundError, ArchiveInProgressError


class TestArchiveManager:
    """存档管理器测试"""

    @pytest.fixture
    def temp_dirs(self):
        """创建临时目录"""
        temp_archive = tempfile.mkdtemp()
        temp_config = tempfile.mkdtemp()

        # 创建测试用的 state.json
        state_data = {
            "P": 7,
            "A": 8,
            "D": 4,
            "客观情境": "测试场景",
            "对应时间": "2026-03-20 10:00:00",
        }
        with open(os.path.join(temp_config, "state.json"), "w", encoding="utf-8") as f:
            json.dump(state_data, f, ensure_ascii=False)

        # 创建测试用的 chat_memory.json
        memory_data = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好呀"},
        ]
        with open(
            os.path.join(temp_config, "chat_memory.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(memory_data, f, ensure_ascii=False)

        yield {"archive": temp_archive, "config": temp_config}

        # 清理
        shutil.rmtree(temp_archive, ignore_errors=True)
        shutil.rmtree(temp_config, ignore_errors=True)

    def test_create_and_load_archive(self, temp_dirs):
        """测试创建和加载存档"""
        manager = ArchiveManager()
        manager.archive_dir = Path(temp_dirs["archive"])
        manager.config_dir = Path(temp_dirs["config"])

        # 创建存档
        result = manager.create_archive("test_slot", "测试存档")
        assert result.success, f"创建存档失败: {result.error}"
        assert result.slot_name == "test_slot"

        # 验证存档文件存在
        archive_path = manager.archive_dir / "test_slot.ember"
        assert archive_path.exists(), "存档文件不存在"

        # 加载存档
        result = manager.load_archive("test_slot")
        assert result.success, f"加载存档失败: {result.error}"
        assert result.manifest is not None

    def test_list_archives(self, temp_dirs):
        """测试列出存档"""
        manager = ArchiveManager()
        manager.archive_dir = Path(temp_dirs["archive"])
        manager.config_dir = Path(temp_dirs["config"])

        # 创建多个存档
        manager.create_archive("slot_1", "存档1")
        manager.create_archive("slot_2", "存档2")

        # 列出存档
        slots = manager.list_archives()
        assert len(slots) == 2

        slot_names = [s.slot_name for s in slots]
        assert "slot_1" in slot_names
        assert "slot_2" in slot_names

    def test_delete_archive(self, temp_dirs):
        """测试删除存档"""
        manager = ArchiveManager()
        manager.archive_dir = Path(temp_dirs["archive"])
        manager.config_dir = Path(temp_dirs["config"])

        # 创建存档
        manager.create_archive("to_delete", "将被删除")

        # 删除存档
        result = manager.delete_archive("to_delete")
        assert result.success

        # 验证存档已删除
        with pytest.raises(ArchiveNotFoundError):
            manager.load_archive("to_delete")

    def test_archive_not_found(self, temp_dirs):
        """测试存档不存在的情况"""
        manager = ArchiveManager()
        manager.archive_dir = Path(temp_dirs["archive"])

        with pytest.raises(ArchiveNotFoundError):
            manager.load_archive("non_existent")


class TestArchiveManifest:
    """存档元数据测试"""

    def test_manifest_serialization(self):
        """测试元数据序列化"""
        manifest = ArchiveManifest(
            version="1.0",
            character_name="依鸣",
            logical_time="2026-03-20 10:00:00",
            description="测试存档",
            stats=ArchiveStats(
                message_count=10,
                memory_count=5,
                entity_count=3,
                relation_count=2,
            ),
        )

        # 序列化
        json_str = manifest.to_json()
        assert json_str is not None

        # 反序列化
        loaded = ArchiveManifest.from_json(json_str)
        assert loaded.version == manifest.version
        assert loaded.character_name == manifest.character_name
        assert loaded.stats.message_count == manifest.stats.message_count


class TestArchiveUtils:
    """存档工具测试"""

    def test_version_compatibility(self):
        """测试版本兼容性检查"""
        from archive.utils.compat import check_version_compatibility

        # 相同版本
        is_compat, msg = check_version_compatibility("1.0", "1.0")
        assert is_compat

        # 兼容版本
        is_compat, msg = check_version_compatibility("1.0", "1.1")
        assert is_compat

    def test_calculate_checksum(self):
        """测试校验和计算"""
        from archive.utils.validate import calculate_checksum

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("test content")
            temp_path = f.name

        try:
            checksum = calculate_checksum(temp_path)
            assert len(checksum) == 32  # MD5 长度
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
