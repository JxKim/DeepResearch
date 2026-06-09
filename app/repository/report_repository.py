from typing import Any
from uuid import uuid4

from app.repository.mongodb import get_mongodb_database
from app.repository.report_storage import get_report_object_storage
from app.schemas import LatestReportResponse, ReportSource, utc_now

COLLECTION_NAME = "report_versions"


def _get_collection():
    """获取报告版本集合对象。

    输入为空，输出为 MongoDB 的 report_versions 集合。数据库连接对象由
    app.repository.mongodb 提供，本模块只负责报告版本读写。
    """

    return get_mongodb_database()[COLLECTION_NAME]


def _dump_sources(sources: list[ReportSource] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把报告来源列表转换为可写入数据库的字典列表。

    输入为 ReportSource 列表或字典列表，输出为字典列表。该函数只做结构转换，
    不负责来源校验。
    """

    dumped_sources: list[dict[str, Any]] = []
    for source in sources:
        if isinstance(source, ReportSource):
            dumped_sources.append(source.model_dump(mode="python"))
        else:
            dumped_sources.append(source)
    return dumped_sources


async def _report_from_document(document: dict[str, Any] | None) -> LatestReportResponse | None:
    """把数据库报告文档转换为最新报告响应结构。

    输入为 MongoDB 返回的报告文档或 None；输出为 LatestReportResponse 或 None。
    新版本 MongoDB 只保存 HTML 存储 URI，读取响应时从对象存储加载 HTML；旧版本
    仍兼容文档内嵌 html 字段。
    """

    if document is None:
        return None
    html = await _load_report_html(document=document)
    return LatestReportResponse(
        project_id=str(document["project_id"]),
        report_id=str(document["report_id"]),
        version=int(document["version"]),
        title=str(document["title"]),
        html=html,
        sources=[ReportSource.model_validate(source) for source in document.get("sources", [])],
        created_at=document["created_at"],
    )


async def _load_report_html(document: dict[str, Any]) -> str:
    html_uri = document.get("html_uri")
    if isinstance(html_uri, str) and html_uri.strip():
        return await get_report_object_storage().read_html(uri=html_uri)
    return str(document.get("html") or "")


async def save_report_version(
    project_id: str,
    title: str,
    html: str,
    sources: list[ReportSource] | list[dict[str, Any]],
) -> LatestReportResponse:
    """保存研究报告版本。

    输入为项目编号、报告标题、HTML 正文和来源列表；输出为保存后的报告版本响应。
    该函数只保存报告成品，不保存事实卡片和洞察卡片。
    """

    latest_document = await _get_collection().find_one(
        {"project_id": project_id},
        sort=[("version", -1)],
        projection={"version": 1},
    )
    next_version = int(latest_document["version"]) + 1 if latest_document else 1
    created_at = utc_now()
    report_id = str(uuid4())
    stored_object = await get_report_object_storage().save_html(
        project_id=project_id,
        report_id=report_id,
        version=next_version,
        html=html,
    )
    report = LatestReportResponse(
        project_id=project_id,
        report_id=report_id,
        version=next_version,
        title=title,
        html=html,
        sources=[ReportSource.model_validate(source) for source in _dump_sources(sources)],
        created_at=created_at,
    )
    document = report.model_dump(mode="python", exclude={"html"})
    document["_id"] = report.report_id
    document["html_uri"] = stored_object.uri
    document["html_path"] = stored_object.path
    document["html_size"] = stored_object.size
    await _get_collection().insert_one(document)
    return report


async def get_latest_report(project_id: str) -> LatestReportResponse | None:
    """读取研究项目的最新报告版本。

    输入为项目编号，输出为最新报告响应结构；项目尚未生成报告时返回 None。
    """

    document = await _get_collection().find_one(
        {"project_id": project_id},
        sort=[("version", -1)],
    )
    return await _report_from_document(document)
