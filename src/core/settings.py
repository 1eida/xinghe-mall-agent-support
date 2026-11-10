"""Configuration for the Qwen / offline customer-support service."""

import logging
from enum import StrEnum
from typing import Literal

from dotenv import find_dotenv
from pydantic import SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    def to_logging_level(self) -> int:
        return getattr(logging, self.value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=find_dotenv(),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    MODE: str | None = None
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    GRACEFUL_SHUTDOWN_TIMEOUT: int = 30
    LOG_LEVEL: LogLevel = LogLevel.WARNING
    AUTH_SECRET: SecretStr | None = None

    CUSTOMER_SUPPORT_MODE: Literal["auto", "mock", "qwen"] = "auto"
    DASHSCOPE_API_KEY: SecretStr | None = None
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DASHSCOPE_MODEL: str = "qwen-plus"
    SQLITE_DB_PATH: str = "checkpoints.db"

    @model_validator(mode="after")
    def validate_qwen_configuration(self) -> "Settings":
        if self.CUSTOMER_SUPPORT_MODE == "qwen" and not self.DASHSCOPE_API_KEY:
            raise ValueError("Qwen mode requires DASHSCOPE_API_KEY")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DEFAULT_MODEL(self) -> str:
        if self.CUSTOMER_SUPPORT_MODE == "qwen" or (
            self.CUSTOMER_SUPPORT_MODE == "auto" and self.DASHSCOPE_API_KEY
        ):
            return self.DASHSCOPE_MODEL
        return "mock"

    @property
    def AVAILABLE_MODELS(self) -> set[str]:
        return {self.DEFAULT_MODEL}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def BASE_URL(self) -> str:
        return f"http://{self.HOST}:{self.PORT}"

    def is_dev(self) -> bool:
        return self.MODE == "dev"


settings = Settings()
