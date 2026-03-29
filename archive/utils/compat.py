"""
版本兼容性检查
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# 当前存档格式版本
CURRENT_ARCHIVE_VERSION = "1.0"

# 版本兼容性映射
# key: 存档版本, value: 兼容的当前版本列表
VERSION_COMPATIBILITY = {
    "1.0": ["1.0", "1.1"],  # 1.0 存档兼容 1.0 和 1.1 系统
}


def parse_version(version: str) -> Tuple[int, int, int]:
    """
    解析版本号

    Args:
        version: 版本字符串 (如 "1.0.0")

    Returns:
        (major, minor, patch) 元组
    """
    try:
        parts = version.split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return (major, minor, patch)
    except Exception:
        return (0, 0, 0)


def check_version_compatibility(
    archive_version: str,
    current_version: str = CURRENT_ARCHIVE_VERSION,
) -> Tuple[bool, str]:
    """
    检查存档版本兼容性

    Args:
        archive_version: 存档版本
        current_version: 当前系统版本

    Returns:
        (是否兼容, 说明信息)
    """
    try:
        # 完全匹配
        if archive_version == current_version:
            return True, "版本完全匹配"

        # 检查兼容性映射
        if archive_version in VERSION_COMPATIBILITY:
            compatible_versions = VERSION_COMPATIBILITY[archive_version]
            if current_version in compatible_versions:
                return (
                    True,
                    f"存档版本 {archive_version} 兼容当前版本 {current_version}",
                )

        # 解析版本号进行主版本检查
        archive_ver = parse_version(archive_version)
        current_ver = parse_version(current_version)

        # 主版本号必须相同
        if archive_ver[0] != current_ver[0]:
            return (
                False,
                f"主版本号不兼容: 存档 {archive_ver[0].x}, 当前 {current_ver[0]}.x",
            )

        # 存档版本不能高于当前版本
        if archive_ver > current_ver:
            return False, f"存档版本 {archive_version} 高于当前版本 {current_version}"

        # 次版本号差异警告
        if archive_ver[1] < current_ver[1]:
            return True, f"存档版本较旧 ({archive_version})，部分功能可能不可用"

        return True, "版本兼容"

    except Exception as e:
        logger.error(f"版本兼容性检查失败: {e}")
        return False, f"版本检查异常: {e}"


def get_current_version() -> str:
    """获取当前存档格式版本"""
    return CURRENT_ARCHIVE_VERSION


def is_breaking_change(old_version: str, new_version: str) -> bool:
    """
    判断是否是破坏性变更

    Args:
        old_version: 旧版本
        new_version: 新版本

    Returns:
        是否是破坏性变更
    """
    old_ver = parse_version(old_version)
    new_ver = parse_version(new_version)

    # 主版本号变化是破坏性变更
    if old_ver[0] != new_ver[0]:
        return True

    return False
