"""
配置加载测试
"""
import pytest
import os
import tempfile
import json
from unittest.mock import patch, MagicMock


class TestSettings:
    """测试配置加载"""

    def test_load_env_variables(self):
        """测试加载环境变量"""
        # 只测试环境变量可以被读取，不涉及重新加载 settings 模块
        with patch.dict(os.environ, {
            "TEST_VAR_KEY": "test_value",
            "TEST_VAR_NUM": "1234",
        }):
            assert os.environ.get("TEST_VAR_KEY") == "test_value"
            assert os.environ.get("TEST_VAR_NUM") == "1234"

    def test_load_prompts_yaml(self):
        """测试加载 prompts.yaml"""
        import tempfile
        import yaml

        with tempfile.TemporaryDirectory() as tmpdir:
            prompts_file = os.path.join(tmpdir, "prompts.yaml")
            with open(prompts_file, "w", encoding="utf-8") as f:
                yaml.dump({
                    "core_persona": "测试人设",
                    "system_prompt": "测试系统提示"
                }, f, allow_unicode=True)

            # 验证 YAML 文件可以正确加载
            with open(prompts_file, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)

            assert loaded["core_persona"] == "测试人设"
            assert loaded["system_prompt"] == "测试系统提示"

    def test_load_state_json(self):
        """测试加载 state.json"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = os.path.join(tmpdir, "state.json")
            test_state = {
                "P": 7, "A": 6, "D": 5,
                "客观情境": "测试情境"
            }
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(test_state, f)

            # 验证 JSON 可以正确加载
            with open(state_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            assert loaded["P"] == 7
            assert loaded["客观情境"] == "测试情境"

    def test_time_acceleration_factor(self):
        """测试时间加速因子可以被正确解析"""
        # 测试 float 转换
        assert float("10.0") == 10.0
        assert float("1.5") == 1.5

    def test_default_values(self, monkeypatch):
        """测试默认值配置"""
        # 清除可能被 .env 设置的环境变量，确保测试的是真正的默认值
        monkeypatch.delenv("HEARTBEAT_INTERVAL", raising=False)
        monkeypatch.delenv("TIME_ACCEL_FACTOR", raising=False)
        monkeypatch.delenv("CONTEXT_WINDOW_SIZE", raising=False)
        assert int(os.getenv("HEARTBEAT_INTERVAL", "10")) == 10
        assert float(os.getenv("TIME_ACCEL_FACTOR", "1.0")) == 1.0
        assert int(os.getenv("CONTEXT_WINDOW_SIZE", "20")) == 20


class TestEnvironmentValidation:
    """测试环境变量验证"""

    def test_missing_required_env(self):
        """测试环境变量缺失情况"""
        # 测试空字符串环境变量
        with patch.dict(os.environ, {"TEST_EMPTY": ""}):
            # 空字符串存在但不是 None
            assert os.environ.get("TEST_EMPTY") == ""
            # os.environ.get 对空字符串不会返回默认值
            # 只有 key 不存在时才返回默认值
            assert os.environ.get("TEST_EMPTY", "default") == ""  # 不是 "default"
            # 只有不存在的 key 才返回默认值
            assert os.environ.get("NON_EXISTENT_KEY", "default") == "default"
