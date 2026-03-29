"""
时间控制模块 - 用于测试时提前/延后系统时间
支持模拟"N天后"的场景
"""
import time
from unittest.mock import patch
import threading


class TimeController:
    """
    时间控制器 - 在测试中使用，支持Mock系统时间

    使用例子：
        controller = TimeController()
        controller.advance_days(3)  # 快进3天
        # 现在 time.time() 会返回+3天的时间戳
    """

    _original_time = None
    _offset_seconds = 0
    _lock = threading.Lock()

    @classmethod
    def advance_seconds(cls, seconds: float):
        """提前指定秒数"""
        with cls._lock:
            cls._offset_seconds += seconds
        print(f"[TimeController] 快进 {seconds} 秒（总偏移：{cls._offset_seconds}s）")

    @classmethod
    def advance_minutes(cls, minutes: float):
        """提前指定分钟"""
        cls.advance_seconds(minutes * 60)

    @classmethod
    def advance_hours(cls, hours: float):
        """提前指定小时"""
        cls.advance_seconds(hours * 3600)

    @classmethod
    def advance_days(cls, days: float):
        """提前指定天数"""
        cls.advance_seconds(days * 86400)

    @classmethod
    def reset(cls):
        """重置到系统真实时间"""
        with cls._lock:
            cls._offset_seconds = 0
        print("[TimeController] 已重置到系统真实时间")

    @classmethod
    def get_current_time(cls):
        """获取当前Mock时间"""
        with cls._lock:
            return time.time() + cls._offset_seconds

    @classmethod
    def patch_time(cls):
        """
        激活时间Mock（在测试代码中调用）

        例子：
            TimeController.advance_days(1)
            with TimeController.patch_time():
                # 在这个块内，所有 time.time() 调用都使用Mock时间
                pass
        """
        return patch('time.time', side_effect=cls.get_current_time)


# 可选：提供全局便捷接口
def advance_days(days):
    """快进N天"""
    TimeController.advance_days(days)

def advance_hours(hours):
    """快进N小时"""
    TimeController.advance_hours(hours)

def advance_minutes(minutes):
    """快进N分钟"""
    TimeController.advance_minutes(minutes)

def reset_time():
    """重置时间"""
    TimeController.reset()

def get_time():
    """获取当前Mock时间戳"""
    return TimeController.get_current_time()
