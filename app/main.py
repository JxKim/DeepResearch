from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.config.config import Settings, get_settings
from app.routers import router as research_projects_router


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例，负责注册基础路由和初始化启动日志。"""

    settings: Settings = get_settings()
    app: FastAPI = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url=f"{settings.api_prefix}/docs",
        openapi_url=f"{settings.api_prefix}/openapi.json",
    )

    # CORS —— 允许本地前端页面跨域调用
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(research_projects_router, prefix=settings.api_prefix)


    @app.get("/health", tags=["系统"])
    async def health_check() -> dict[str, str]:
        """返回服务健康状态，用于本地调试、容器探针和部署检查。"""

        return {"status": "ok"}


    # 静态文件放在最后挂载，确保 API 路由优先匹配
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

    return app


app: FastAPI = create_app()
