from loguru import logger
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.config.config import Settings, get_settings

_mongodb_client: AsyncMongoClient | None = None


def get_mongodb_client() -> AsyncMongoClient:
    """获取 MongoDB 异步客户端连接池。

    输入为空，输出为当前进程复用的 AsyncMongoClient。PyMongo 客户端自身维护连接池，
    因此本模块只创建一次客户端，不在每次 repository 调用时重复建立连接。
    """

    global _mongodb_client
    if _mongodb_client is None:
        settings: Settings = get_settings()
        _mongodb_client = AsyncMongoClient(
            settings.mongodb_uri,
            uuidRepresentation="standard",
            serverSelectionTimeoutMS=5000,
        )
        logger.info("MongoDB 客户端已初始化，database={}", settings.mongodb_database)
    return _mongodb_client


def get_mongodb_database() -> AsyncDatabase:
    """获取 MongoDB 数据库对象。

    输入为空，输出为配置项 `mongodb_database` 对应的数据库对象。repository 模块通过
    该数据库对象选择集合并执行读写操作。
    """

    settings: Settings = get_settings()
    return get_mongodb_client()[settings.mongodb_database]


async def ping_mongodb() -> None:
    """检查 MongoDB 连接是否可用。

    输入为空，输出为空。该函数用于服务启动或健康检查阶段验证数据库连接，不返回
    业务数据。
    """

    await get_mongodb_database().command("ping")


async def close_mongodb_client() -> None:
    """关闭当前进程内的 MongoDB 客户端连接池。

    输入为空，输出为空。该函数供 FastAPI lifespan 或 shutdown 阶段调用，避免服务
    退出时遗留连接资源。
    """

    global _mongodb_client
    if _mongodb_client is not None:
        _mongodb_client.close()
        _mongodb_client = None
        logger.info("MongoDB 客户端已关闭")

if __name__ == "__main__":
    print("hello")
