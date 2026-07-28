from datetime import datetime
from typing import Any

from app.repository.mongodb import get_mongodb_database
from app.schemas import (
    OutlineNode,
    ProjectStatus,
    ReportSource,
    ResearchProjectCreate,
    utc_now,
)

COLLECTION_NAME = "research_projects"


def _get_collection():
    """获取研究项目集合对象。

    输入为空，输出为 MongoDB 的 research_projects 集合。数据库连接对象由
    app.repository.mongodb 提供，本模块只负责项目相关读写。
    """

    return get_mongodb_database()[COLLECTION_NAME]


def _clean_document(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """清理 MongoDB 内部字段并恢复稳定枚举字段。

    输入为数据库原始项目文档或 None；输出为业务层可直接使用的 dict 或 None。
    该函数不做业务校验，只处理数据库字段到业务字段的转换。
    """

    if document is None:
        return None
    document.pop("_id", None)
    if "status" in document:
        document["status"] = ProjectStatus(str(document["status"]))
    return document


def _dump_outline(outline: list[OutlineNode] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把大纲节点转换为可写入 MongoDB 的字典列表。

    输入为 OutlineNode 列表或字典列表，输出为字典列表。该函数兼容后续 Agent 返回
    Pydantic 结构或普通 dict 的两种情况。
    """

    dumped_outline: list[dict[str, Any]] = []
    for node in outline:
        if isinstance(node, OutlineNode):
            dumped_outline.append(node.model_dump(mode="python"))
        else:
            dumped_outline.append(node)
    return dumped_outline


def _dump_sources(sources: list[ReportSource] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把来源列表转换为可写入 MongoDB 的字典列表。"""

    dumped_sources: list[dict[str, Any]] = []
    for source in sources:
        if isinstance(source, ReportSource):
            dumped_sources.append(source.model_dump(mode="python"))
        else:
            dumped_sources.append(source)
    return dumped_sources


async def create_project(
    project_id: str,
    request: ResearchProjectCreate,
    topic: str,
    status: ProjectStatus,
    created_at: datetime,
) -> dict[str, Any]:
    """创建研究项目记录。

    输入为项目编号、创建请求、主题、初始状态和创建时间；输出为写入后的项目文档。
    该函数只负责项目基础信息持久化，不创建任务、不启动 Agent。
    """

    document: dict[str, Any] = {
        "_id": project_id,
        "project_id": project_id,
        "topic": topic,
        "request": request.model_dump(mode="python"),
        "status": status,
        "outline": [],
        "confirmed_outline": [],
        "research_brief": None,
        "sections": [],
        "sources": [],
        "created_at": created_at,
        "updated_at": created_at,
    }
    await _get_collection().insert_one(document)
    return _clean_document(document) or {}


async def get_project(project_id: str) -> dict[str, Any] | None:
    """根据项目编号读取研究项目。

    输入为项目编号，输出为项目文档；项目不存在时返回 None。
    """

    document = await _get_collection().find_one({"project_id": project_id})
    return _clean_document(document)


async def update_project_status(project_id: str, status: ProjectStatus) -> None:
    """更新研究项目主流程状态。

    输入为项目编号和目标状态，输出为空。该函数只更新状态和更新时间。
    """

    await _get_collection().update_one(
        {"project_id": project_id},
        {"$set": {"status": status, "updated_at": utc_now()}},
    )


async def get_outline(project_id: str) -> list[OutlineNode]:
    """读取研究项目当前大纲草案。

    输入为项目编号，输出为大纲节点列表；大纲不存在时返回空列表。
    """

    document = await _get_collection().find_one({"project_id": project_id}, {"outline": 1})
    if document is None:
        return []
    return [OutlineNode.model_validate(node) for node in document.get("outline", [])]


async def get_confirmed_outline(project_id: str) -> list[OutlineNode]:
    """读取研究项目已确认大纲。

    输入为项目编号，输出为已确认大纲节点列表；如果 confirmed_outline 尚未单独保存，
    则回退读取 outline 字段。
    """

    document = await _get_collection().find_one(
        {"project_id": project_id},
        {"outline": 1, "confirmed_outline": 1},
    )
    if document is None:
        return []
    outline = document.get("confirmed_outline") or document.get("outline", [])
    return [OutlineNode.model_validate(node) for node in outline]


async def save_research_brief_and_outline(
    project_id: str,
    research_brief: Any,
    outline: list[OutlineNode] | list[dict[str, Any]],
) -> None:
    """保存研究任务书和大纲草案。

    输入为项目编号、研究任务书和大纲节点列表，输出为空。该函数用于大纲生成任务
    完成后的结果落库。
    """

    await _get_collection().update_one(
        {"project_id": project_id},
        {
            "$set": {
                "research_brief": _dump_value(research_brief),
                "outline": _dump_outline(outline),
                "updated_at": utc_now(),
            }
        },
    )


async def save_outline(
    project_id: str,
    outline: list[OutlineNode] | list[dict[str, Any]],
) -> None:
    """保存研究大纲草案。

    输入为项目编号和大纲节点列表，输出为空。该函数用于大纲修改任务完成后覆盖
    当前大纲草案。
    """

    await _get_collection().update_one(
        {"project_id": project_id},
        {"$set": {"outline": _dump_outline(outline), "updated_at": utc_now()}},
    )


async def save_confirmed_outline(
    project_id: str,
    outline: list[OutlineNode] | list[dict[str, Any]],
) -> None:
    """保存用户确认后的研究大纲。

    输入为项目编号和大纲节点列表，输出为空。当前 router 只更新项目状态，后续如果
    需要保留确认快照，可以调用该函数写入 confirmed_outline。
    """

    await _get_collection().update_one(
        {"project_id": project_id},
        {"$set": {"confirmed_outline": _dump_outline(outline), "updated_at": utc_now()}},
    )


async def clear_research_sections(project_id: str) -> None:
    """清空研究章节草稿。

    输入为项目编号，输出为空。该函数在重新执行报告研究任务前调用，避免旧章节或占位
    章节混入本次研究结果。
    """

    await _get_collection().update_one(
        {"project_id": project_id},
        {
            "$set": {
                "sections": [],
                "sources": [],
                "updated_at": utc_now(),
            }
        },
    )


async def upsert_research_section(project_id: str, section: dict[str, Any]) -> None:
    """按 section_id 保存或覆盖单个研究章节。

    输入为项目编号和已通过校验的 ResearchSection 字典，输出为空。该方法用于主研究
    智能体逐章节落库，避免最后一次性解析大 JSON。
    """

    section_id = section.get("section_id")
    await _get_collection().update_one(
        {"project_id": project_id},
        {"$pull": {"sections": {"section_id": section_id}}},
    )
    await _get_collection().update_one(
        {"project_id": project_id},
        {"$push": {"sections": section}, "$set": {"updated_at": utc_now()}},
    )


async def upsert_research_sources(project_id: str, sources: list[dict[str, Any]]) -> None:
    """按 URL 优先合并保存全项目研究来源。

    source_id 可能是主智能体每个章节内从 source-1 重新开始的局部编号，不能作为
    跨章节去重键。有 URL 时按 URL 去重；无 URL 时用 source_type/title 兜底。
    """

    now = utc_now()
    for source in sources:
        source_key = _source_dedupe_key(source)
        if source_key is None:
            continue
        source_filter = (
            {"url": source_key}
            if source.get("url")
            else {
                "url": {"$in": [None, ""]},
                "source_type": source.get("source_type"),
                "title": source.get("title"),
            }
        )
        await _get_collection().update_one(
            {"project_id": project_id},
            {"$pull": {"sources": source_filter}},
        )
        await _get_collection().update_one(
            {"project_id": project_id},
            {"$push": {"sources": source}, "$set": {"updated_at": now}},
        )


def _source_dedupe_key(source: dict[str, Any]) -> str | None:
    url = str(source.get("url") or "").strip()
    if url:
        return url
    title = str(source.get("title") or "").strip()
    source_type = str(source.get("source_type") or "").strip()
    if not title:
        return None
    return f"{source_type}:{title}"


async def get_research_sections(project_id: str) -> list[dict[str, Any]]:
    """读取当前项目已落库的研究章节。

    输入为项目编号，输出为 ResearchSection 字典列表。返回值按 section_id 字符串排序，
    让报告渲染阶段得到稳定章节顺序。
    """

    document = await _get_collection().find_one({"project_id": project_id}, {"sections": 1})
    if document is None:
        return []
    sections = [section for section in document.get("sections", []) if isinstance(section, dict)]
    return sorted(sections, key=lambda section: str(section.get("section_id") or ""))


async def get_research_sources(project_id: str) -> list[dict[str, Any]]:
    """读取当前项目已去重的研究来源。"""

    document = await _get_collection().find_one({"project_id": project_id}, {"sources": 1})
    if document is None:
        return []
    return [source for source in document.get("sources", []) if isinstance(source, dict)]


def _dump_value(value: Any) -> Any:
    """把 Pydantic 对象或普通对象转换为可保存的值。

    输入为任意值，输出为 MongoDB 可保存的基础结构。该函数主要兼容 Agent 结构化
    输出对象，不承担业务字段校验。
    """

    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    return value
