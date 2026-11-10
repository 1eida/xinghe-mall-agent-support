import logging
import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from core.settings import LogLevel, Settings


@pytest.fixture(autouse=True)
def clean_environment():
    with patch.dict(os.environ, {}, clear=True):
        yield


def test_offline_startup_needs_no_api_key():
    settings = Settings(_env_file=None)
    assert settings.DEFAULT_MODEL == "mock"
    assert settings.AVAILABLE_MODELS == {"mock"}
    assert settings.BASE_URL == "http://0.0.0.0:8080"


def test_auto_uses_qwen_when_key_is_configured():
    settings = Settings(DASHSCOPE_API_KEY="test-key", _env_file=None)
    assert settings.DEFAULT_MODEL == "qwen-plus"
    assert settings.AVAILABLE_MODELS == {"qwen-plus"}
    assert "test-key" not in repr(settings)


def test_explicit_mock_ignores_qwen_key():
    settings = Settings(CUSTOMER_SUPPORT_MODE="mock", DASHSCOPE_API_KEY="test-key", _env_file=None)
    assert settings.DEFAULT_MODEL == "mock"


def test_explicit_qwen_requires_credentials():
    with pytest.raises(ValidationError, match="DASHSCOPE_API_KEY"):
        Settings(CUSTOMER_SUPPORT_MODE="qwen", _env_file=None)


def test_qwen_model_can_be_configured():
    settings = Settings(
        CUSTOMER_SUPPORT_MODE="qwen",
        DASHSCOPE_API_KEY="test-key",
        DASHSCOPE_MODEL="qwen-flash",
        _env_file=None,
    )
    assert settings.DEFAULT_MODEL == "qwen-flash"


def test_invalid_mode_is_rejected():
    with pytest.raises(ValidationError, match="CUSTOMER_SUPPORT_MODE"):
        Settings(CUSTOMER_SUPPORT_MODE="unknown", _env_file=None)


def test_server_settings_from_environment():
    with patch.dict(os.environ, {"HOST": "127.0.0.1", "PORT": "9090", "MODE": "dev"}):
        settings = Settings(_env_file=None)
    assert settings.BASE_URL == "http://127.0.0.1:9090"
    assert settings.is_dev()
    assert not Settings(MODE="prod", _env_file=None).is_dev()


@pytest.mark.parametrize("level", list(LogLevel))
def test_log_level_conversion(level):
    assert level.to_logging_level() == getattr(logging, level.value)


def test_invalid_log_level_is_rejected():
    with pytest.raises(ValidationError, match="LOG_LEVEL"):
        Settings(LOG_LEVEL="INVALID", _env_file=None)
