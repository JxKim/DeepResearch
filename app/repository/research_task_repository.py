from datetime import datetime

from app.repository.mongodb import get_mongodb_database
from app.schemas import TaskStatus, TaskStatusResponse, TaskType, utc_now

COLLECTION_NAME = "research_tasks"


def _get_collection():
    """获取研究任务集合对象。

    输入为空，输出为 MongoDB 的 research_tasks 集合。数据库连接对象由
    app.repository.mongodb 提供，本模块只负责使用连接对象进行任务读写。
    """

    return get_mongodb_database()[COLLECTION_NAME]


def _task_from_document(document: dict[str, object] | None) -> TaskStatusResponse | None:
    """把数据库任务文档转换为接口任务状态结构。

    输入为 MongoDB 返回的任务文档或 None；输出为 TaskStatusResponse 或 None。
    该函数只处理字段映射，不访问数据库。
    """

    if document is None:
        return None
    return TaskStatusResponse(
        task_id=str(document["task_id"]),
        project_id=str(document["project_id"]),
        task_type=TaskType(str(document["task_type"])),
        status=TaskStatus(str(document["status"])),
        message=str(document["message"]),
        created_at=document["created_at"],  # type: ignore[arg-type]
        updated_at=document["updated_at"],  # type: ignore[arg-type]
    )


async def create_task(
    task_id: str,
    project_id: str,
    task_type: TaskType,
    status: TaskStatus,
    message: str,
    created_at: datetime,
    updated_at: datetime,
) -> TaskStatusResponse:
    """创建后台任务记录。

    输入为任务编号、项目编号、任务类型、任务状态、状态说明和时间；输出为创建后的
    TaskStatusResponse。该函数只保存任务元数据，不启动后台任务。
    """

    task = TaskStatusResponse(
        task_id=task_id,
        project_id=project_id,
        task_type=task_type,
        status=status,
        message=message,
        created_at=created_at,
        updated_at=updated_at,
    )
    document = task.model_dump(mode="python")
    document["_id"] = task_id
    await _get_collection().insert_one(document)
    return task


async def get_task(task_id: str) -> TaskStatusResponse | None:
    """根据任务编号读取后台任务状态。

    输入为任务编号，输出为任务状态结构；任务不存在时返回 None。
    """

    document = await _get_collection().find_one({"task_id": task_id})
    return _task_from_document(document)


async def mark_task_running(task_id: str, message: str) -> None:
    """把后台任务标记为运行中。

    输入为任务编号和状态说明，输出为空。该函数只更新任务状态和更新时间。
    """

    await _update_task_status(task_id=task_id, status=TaskStatus.RUNNING, message=message)


async def mark_task_succeeded(task_id: str, message: str) -> None:
    """把后台任务标记为执行成功。

    输入为任务编号和状态说明，输出为空。该函数只更新任务状态和更新时间。
    """

    await _update_task_status(task_id=task_id, status=TaskStatus.SUCCEEDED, message=message)


async def mark_task_failed(task_id: str, message: str) -> None:
    """把后台任务标记为执行失败。

    输入为任务编号和失败说明，输出为空。失败说明只能保存必要摘要，不保存敏感原文。
    """

    await _update_task_status(task_id=task_id, status=TaskStatus.FAILED, message=message)


async def _update_task_status(task_id: str, status: TaskStatus, message: str) -> None:
    """统一更新后台任务状态。

    输入为任务编号、目标状态和状态说明，输出为空。该函数是任务状态更新的内部复用
    入口，避免不同状态方法重复拼写更新字段。
    """

    await _get_collection().update_one(
        {"task_id": task_id},
        {
            "$set": {
                "status": status,
                "message": message,
                "updated_at": utc_now(),
            }
        },
    )
