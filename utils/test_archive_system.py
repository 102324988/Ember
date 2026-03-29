"""
存档系统测试脚本

在 Ember 环境中测试存档功能。
"""

import os
import sys
import json
import time
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from archive import ArchiveManager, ArchiveManifest, ArchiveStats
from archive.exceptions import ArchiveNotFoundError, ArchiveInProgressError


def print_header(title: str):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_result(name: str, success: bool, message: str = ""):
    """打印测试结果"""
    status = "✅ 通过" if success else "❌ 失败"
    print(f"  {status} - {name}")
    if message:
        print(f"         {message}")


def test_basic_operations():
    """测试基本操作"""
    print_header("测试 1: 基本存档操作")

    manager = ArchiveManager()

    # 测试创建存档
    print("\n  创建测试存档 'test_slot_1'...")
    result = manager.create_archive("test_slot_1", "测试存档 #1")
    print_result("创建存档", result.success, result.message)

    if result.success:
        print(f"         存档路径: {manager.archive_dir / 'test_slot_1.ember'}")
        if result.manifest:
            print(f"         角色名: {result.manifest.character_name}")
            print(f"         逻辑时间: {result.manifest.logical_time}")

    # 测试列出存档
    print("\n  列出所有存档...")
    slots = manager.list_archives()
    print_result("列出存档", len(slots) > 0, f"共 {len(slots)} 个存档")
    for slot in slots:
        print(
            f"         - {slot.slot_name}: {slot.description} ({slot.file_size} bytes)"
        )

    # 测试预览存档
    print("\n  预览存档信息...")
    manifest = manager.get_archive_preview("test_slot_1")
    if manifest:
        print_result("预览存档", True)
        print(f"         版本: {manifest.version}")
        print(f"         创建时间: {manifest.created_at}")
        print(f"         描述: {manifest.description}")
        if manifest.stats:
            print(f"         消息数: {manifest.stats.message_count}")
            print(f"         记忆数: {manifest.stats.memory_count}")
    else:
        print_result("预览存档", False, "无法读取存档")

    # 测试加载存档
    print("\n  加载存档 'test_slot_1'...")
    result = manager.load_archive("test_slot_1")
    print_result("加载存档", result.success, result.message)

    # 测试删除存档
    print("\n  删除存档 'test_slot_1'...")
    result = manager.delete_archive("test_slot_1")
    print_result("删除存档", result.success, result.message)

    # 验证删除
    slots_after = manager.list_archives()
    print_result("验证删除", "test_slot_1" not in [s.slot_name for s in slots_after])


def test_quick_save_load():
    """测试快速存档/读档"""
    print_header("测试 2: 快速存档/读档")

    manager = ArchiveManager()

    # 快速存档
    print("\n  执行快速存档...")
    result = manager.quick_save()
    print_result("快速存档", result.success, result.message)

    # 快速读档
    print("\n  执行快速读档...")
    result = manager.quick_load()
    print_result("快速读档", result.success, result.message)

    # 清理
    manager.delete_archive("quick_save")
    print("\n  已清理快速存档")


def test_multiple_slots():
    """测试多存档槽"""
    print_header("测试 3: 多存档槽管理")

    manager = ArchiveManager()

    # 创建多个存档
    slots_to_create = ["slot_a", "slot_b", "slot_c"]
    for slot_name in slots_to_create:
        result = manager.create_archive(slot_name, f"测试存档 {slot_name}")
        print_result(f"创建 {slot_name}", result.success)

    # 列出存档
    print("\n  当前列表:")
    slots = manager.list_archives()
    for slot in slots:
        print(f"         - {slot.slot_name}: {slot.description}")

    # 清理
    print("\n  清理测试存档...")
    for slot_name in slots_to_create:
        manager.delete_archive(slot_name)
    print_result("清理完成", True)


def test_error_handling():
    """测试错误处理"""
    print_header("测试 4: 错误处理")

    manager = ArchiveManager()

    # 测试加载不存在的存档
    print("\n  尝试加载不存在的存档...")
    try:
        manager.load_archive("non_existent_slot")
        print_result("错误处理", False, "应该抛出异常")
    except ArchiveNotFoundError as e:
        print_result("错误处理", True, f"正确抛出 ArchiveNotFoundError: {e.message}")
    except Exception as e:
        print_result("错误处理", False, f"错误的异常类型: {type(e).__name__}")


def test_manifest():
    """测试元数据"""
    print_header("测试 5: 元数据序列化")

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
    print_result("序列化", json_str is not None)
    print(f"         JSON 长度: {len(json_str)} 字符")

    # 反序列化
    loaded = ArchiveManifest.from_json(json_str)
    print_result("反序列化", loaded is not None)
    print(f"         版本匹配: {loaded.version == manifest.version}")
    print(f"         角色名匹配: {loaded.character_name == manifest.character_name}")
    print(
        f"         消息数匹配: {loaded.stats.message_count == manifest.stats.message_count}"
    )


def test_progress_callback():
    """测试进度回调"""
    print_header("测试 6: 进度回调")

    progress_log = []

    def progress_callback(message: str, progress: int):
        progress_log.append((message, progress))
        print(f"         [{progress:3d}%] {message}")

    manager = ArchiveManager()
    manager.set_progress_callback(progress_callback)

    print("\n  创建存档 (带进度回调)...")
    result = manager.create_archive("progress_test", "进度测试")
    print_result("创建完成", result.success, f"共 {len(progress_log)} 个进度事件")

    # 清理
    manager.delete_archive("progress_test")


def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("  Ember 存档系统测试")
    print("  时间:", time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    try:
        test_basic_operations()
        test_quick_save_load()
        test_multiple_slots()
        test_error_handling()
        test_manifest()
        test_progress_callback()

        print_header("测试完成")
        print("\n  所有测试已执行完毕！")

    except Exception as e:
        print_header("测试出错")
        print(f"\n  错误: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
