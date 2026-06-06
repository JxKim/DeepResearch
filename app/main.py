from typing import Any

from fastapi import FastAPI
from loguru import logger

from app.api.research_projects import router as research_projects_router
from app.core.config import Settings, get_settings


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例，负责注册基础路由和初始化启动日志。"""

    settings: Settings = get_settings()
    app: FastAPI = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )
    app.include_router(research_projects_router, prefix=settings.api_prefix)

    @app.on_event("startup")
    async def log_startup() -> None:
        """记录服务启动信息，便于确认当前环境和版本。"""

        logger.info(
            "后端服务启动完成，环境：{}，版本：{}",
            settings.environment,
            settings.app_version,
        )

    @app.get("/health", tags=["系统"])
    async def health_check() -> dict[str, str]:
        """返回服务健康状态，用于本地调试、容器探针和部署检查。"""

        return {"status": "ok"}

    @app.get(f"{settings.api_prefix}/system/info", tags=["系统"])
    async def system_info() -> dict[str, Any]:
        """返回系统基础信息，用于前端确认后端服务版本和运行环境。"""

        return {
            "app_name": settings.app_name,
            "app_version": settings.app_version,
            "environment": settings.environment,
        }

    return app


app: FastAPI = create_app()
