"""
存档系统自定义异常
"""


class ArchiveError(Exception):
    """存档操作基础异常"""

    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ArchiveNotFoundError(ArchiveError):
    """存档不存在"""

    def __init__(self, slot_name: str):
        super().__init__(f"存档 '{slot_name}' 不存在", {"slot_name": slot_name})


class ArchiveCorruptedError(ArchiveError):
    """存档文件损坏"""

    def __init__(self, slot_name: str, reason: str = ""):
        message = f"存档 '{slot_name}' 已损坏"
        if reason:
            message += f": {reason}"
        super().__init__(message, {"slot_name": slot_name, "reason": reason})


class ArchiveVersionError(ArchiveError):
    """存档版本不兼容"""

    def __init__(self, archive_version: str, current_version: str):
        super().__init__(
            f"存档版本 '{archive_version}' 与当前版本 '{current_version}' 不兼容",
            {"archive_version": archive_version, "current_version": current_version},
        )


class ArchiveInProgressError(ArchiveError):
    """存档操作正在进行中"""

    def __init__(self, operation: str):
        super().__init__(
            f"存档操作 '{operation}' 正在进行中，请稍后再试",
            {"operation": operation},
        )


class ArchiveExportError(ArchiveError):
    """导出失败"""

    def __init__(self, component: str, reason: str):
        super().__init__(
            f"导出 '{component}' 失败: {reason}",
            {"component": component, "reason": reason},
        )


class ArchiveImportError(ArchiveError):
    """导入失败"""

    def __init__(self, component: str, reason: str):
        super().__init__(
            f"导入 '{component}' 失败: {reason}",
            {"component": component, "reason": reason},
        )
