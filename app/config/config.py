from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """系统配置对象，负责从环境变量读取后端服务运行所需的基础配置。"""

    app_name: str = "AI 研究报告工作台"
    app_version: str = "0.1.0"
    environment: str = "local"
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def get_settings() -> Settings:
    """获取系统配置，负责创建当前运行环境下的配置对象。"""

    return Settings()
