from typing import Any

from app.repository import research_project_repository

PLACEHOLDER_MARKERS = [
    "占位",
    "待生成",
    "稍后补充",
    "待补充",
    "TODO",
    "真实内容将在",
    "尚未接入真实",
]
CONFIDENCE_VALUES = {"high", "medium", "low"}
RISK_TYPES = {
    "evidence_gap",
    "source_conflict",
    "stale_data",
    "uncertainty",
    "execution_risk",
}
SEVERITY_VALUES = {"high", "medium", "low"}


async def save_research_section(project_id: str, section: dict[str, Any]) -> dict[str, Any]:
    """保存单个已完成研究章节。

    输入为项目编号和一个 ResearchSection 字典；输出为保存结果。该工具只接受完整正文
    章节，不接受占位内容。校验失败时返回 ok=false 和错误列表，让主研究智能体按错误
    修改后重试。
    """

    errors = await _validate_section(project_id=project_id, section=section)
    if errors:
        return {"ok": False, "errors": errors}

    normalized_sources = _normalize_sources(section.get("sources"))
    normalized_section = _normalize_section(section, sources=normalized_sources)
    await research_project_repository.upsert_research_section(
        project_id=project_id,
        section=normalized_section,
    )
    if normalized_sources:
        await research_project_repository.upsert_research_sources(
            project_id=project_id,
            sources=normalized_sources,
        )
    return {
        "ok": True,
        "project_id": project_id,
        "section_id": normalized_section["section_id"],
        "sources_merged": len(normalized_sources),
        "message": "research section saved",
    }


async def _validate_section(project_id: str, section: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(section, dict):
        return ["section 必须是对象"]

    project = await research_project_repository.get_project(project_id=project_id)
    if project is None:
        return [f"project_id 不存在: {project_id}"]

    section_id = _clean_text(section.get("section_id"))
    title = _clean_text(section.get("title"))
    body = _clean_text(section.get("body"))
    key_findings = section.get("key_findings")
    risks = section.get("risks")
    incoming_sources = _normalize_sources(section.get("sources"))
    known_source_ids = _source_ids(incoming_sources)
    referenced_source_ids = _referenced_source_ids_from_section(section)
    outline_nodes = project.get("confirmed_outline") or project.get("outline") or []

    if not section_id:
        errors.append("section.section_id 不能为空")
    elif section_id not in _outline_node_ids(outline_nodes):
        errors.append(f"section.section_id 不在已确认大纲中: {section_id}")
    if not title:
        errors.append("section.title 不能为空")
    if len(body) < 120:
        errors.append("section.body 必须是完整章节正文，长度至少 120 字符")
    if _contains_placeholder(body):
        errors.append("section.body 包含占位或待补充文案")
    if not isinstance(key_findings, list) or not key_findings:
        errors.append("section.key_findings 至少需要 1 条非空关键发现")
    else:
        for index, item in enumerate(key_findings, start=1):
            if not isinstance(item, dict):
                errors.append(f"section.key_findings[{index}] 必须是对象")
                continue
            claim = _clean_text(item.get("claim") or item.get("summary") or item.get("title"))
            if not claim:
                errors.append(f"section.key_findings[{index}].claim 不能为空")
            if _contains_placeholder(claim):
                errors.append(f"section.key_findings[{index}].claim 包含占位文案")
            if not _clean_string_list(item.get("source_ids")):
                errors.append(f"section.key_findings[{index}].source_ids 至少需要 1 个来源引用")
    if referenced_source_ids and not incoming_sources and not known_source_ids:
        errors.append("section.sources 必须包含 key_findings/risks 引用到的来源详情")
    missing_source_ids = referenced_source_ids - known_source_ids
    if missing_source_ids:
        errors.append(
            "section.sources 缺少以下 source_id 的来源详情: "
            + ", ".join(sorted(missing_source_ids))
        )
    sources_by_id = {
        source["source_id"]: source
        for source in incoming_sources
        if source.get("source_id")
    }
    for index, source in enumerate(incoming_sources, start=1):
        source_id = source.get("source_id") or f"第 {index} 个来源"
        if _source_requires_url(source) and not _is_http_url(source.get("url")):
            errors.append(
                f"section.sources[{source_id}].url 不能为空，公开来源必须提供 http(s) URL"
            )
    for source_id in sorted(referenced_source_ids):
        source = sources_by_id.get(source_id)
        if source and _source_requires_url(source) and not _is_http_url(source.get("url")):
            errors.append(f"章节引用的公开来源 {source_id} 缺少 http(s) URL")
    if isinstance(risks, list):
        for index, risk in enumerate(risks, start=1):
            if not isinstance(risk, dict):
                errors.append(f"section.risks[{index}] 必须是对象")
                continue
            description = _clean_text(
                risk.get("description") or risk.get("summary") or risk.get("title")
            )
            if not description:
                errors.append(f"section.risks[{index}].description 不能为空")
            if _contains_placeholder(description):
                errors.append(f"section.risks[{index}].description 包含占位文案")
    elif risks is not None:
        errors.append("section.risks 必须是数组")

    return errors


def _normalize_section(
    section: dict[str, Any],
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "section_id": _clean_text(section.get("section_id")),
        "title": _clean_text(section.get("title")),
        "summary": _clean_text(section.get("summary")) or None,
        "body": _clean_text(section.get("body")),
        "key_findings": _normalize_key_findings(section.get("key_findings")),
        "sources": sources if sources is not None else _normalize_sources(section.get("sources")),
        "tables": [item for item in _ensure_list(section.get("tables")) if isinstance(item, dict)],
        "charts": [item for item in _ensure_list(section.get("charts")) if isinstance(item, dict)],
        "risks": _normalize_risks(section.get("risks")),
    }


def _normalize_sources(value: Any) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for index, item in enumerate(_ensure_list(value), start=1):
        if not isinstance(item, dict):
            continue
        source_id = (
            _clean_text(item.get("source_id"))
            or _clean_text(item.get("id"))
            or f"source-{index}"
        )
        title = _clean_text(item.get("title"))
        source_type = _clean_text(item.get("source_type")) or "unknown"
        url = _clean_text(item.get("url")) or None
        published_at = _clean_text(item.get("published_at")) or None
        summary = _clean_text(item.get("summary")) or None
        if not title:
            continue
        sources.append(
            {
                "source_id": source_id,
                "title": title,
                "url": url,
                "published_at": published_at,
                "source_type": source_type,
                "summary": summary,
            }
        )
    return sources


def _normalize_key_findings(value: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(_ensure_list(value), start=1):
        if not isinstance(item, dict):
            continue
        claim = _clean_text(item.get("claim") or item.get("summary") or item.get("title"))
        if not claim:
            continue
        findings.append(
            {
                "finding_id": _clean_text(item.get("finding_id")) or f"finding-{index}",
                "claim": claim,
                "source_ids": _clean_string_list(item.get("source_ids")),
                "confidence": _normalize_choice(
                    item.get("confidence"),
                    CONFIDENCE_VALUES,
                    "medium",
                ),
            }
        )
    return findings


def _normalize_risks(value: Any) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for index, item in enumerate(_ensure_list(value), start=1):
        if not isinstance(item, dict):
            continue
        description = _clean_text(
            item.get("description") or item.get("summary") or item.get("title")
        )
        if not description:
            continue
        risks.append(
            {
                "risk_id": _clean_text(item.get("risk_id")) or f"risk-{index}",
                "description": description,
                "source_ids": _clean_string_list(item.get("source_ids")),
                "risk_type": _normalize_choice(item.get("risk_type"), RISK_TYPES, "uncertainty"),
                "severity": _normalize_choice(item.get("severity"), SEVERITY_VALUES, "medium"),
            }
        )
    return risks


def _referenced_source_ids_from_section(section: dict[str, Any]) -> set[str]:
    source_ids: set[str] = set()
    source_ids.update(_referenced_source_ids(section.get("key_findings")))
    source_ids.update(_referenced_source_ids(section.get("risks")))
    return source_ids


def _referenced_source_ids(items: Any) -> set[str]:
    source_ids: set[str] = set()
    for item in _ensure_list(items):
        if not isinstance(item, dict):
            continue
        source_ids.update(
            _clean_text(source_id)
            for source_id in _ensure_list(item.get("source_ids"))
            if _clean_text(source_id)
        )
    return source_ids


def _source_ids(value: Any) -> set[str]:
    source_ids: set[str] = set()
    for item in _ensure_list(value):
        if not isinstance(item, dict):
            continue
        source_id = _clean_text(item.get("source_id")) or _clean_text(item.get("id"))
        if source_id:
            source_ids.add(source_id)
    return source_ids


def _source_requires_url(source: dict[str, Any]) -> bool:
    source_type = _clean_text(source.get("source_type"))
    return source_type not in {"internal_knowledge_base"}


def _is_http_url(value: Any) -> bool:
    url = _clean_text(value)
    return url.startswith(("http://", "https://"))


def _outline_node_ids(nodes: list[Any]) -> set[str]:
    node_ids: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = _clean_text(node.get("node_id"))
        if node_id:
            node_ids.add(node_id)
        node_ids.update(_outline_node_ids(node.get("children") or []))
    return node_ids


def _contains_placeholder(text: str) -> bool:
    return any(marker in text for marker in PLACEHOLDER_MARKERS)


def _ensure_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_string_list(value: Any) -> list[str]:
    return [_clean_text(item) for item in _ensure_list(value) if _clean_text(item)]


def _normalize_choice(value: Any, allowed: set[str], fallback: str) -> str:
    text = _clean_text(value).lower()
    return text if text in allowed else fallback


def _clean_text(value: Any) -> str:
    return str(value or "").strip()
