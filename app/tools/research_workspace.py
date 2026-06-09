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


async def save_research_section(project_id: str, section: dict[str, Any]) -> dict[str, Any]:
    """保存单个已完成研究章节。

    输入为项目编号和一个 ResearchSection 字典；输出为保存结果。该工具只接受完整正文
    章节，不接受占位内容。校验失败时返回 ok=false 和错误列表，让主研究智能体按错误
    修改后重试。
    """

    errors = await _validate_section(project_id=project_id, section=section)
    if errors:
        return {"ok": False, "errors": errors}

    normalized_sources = await _normalize_section_sources(
        project_id=project_id,
        section=section,
    )
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
        "sources_saved": len(normalized_sources),
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
    evidence_chain = section.get("evidence_chain")
    risks = section.get("risks")
    incoming_sources = _normalize_sources(section.get("sources"))
    existing_sources = project.get("sources") if isinstance(project, dict) else []
    known_source_ids = _source_ids(incoming_sources) | _source_ids(existing_sources)
    referenced_source_ids: set[str] = set()

    if not section_id:
        errors.append("section.section_id 不能为空")
    elif section_id not in _outline_node_ids(project.get("confirmed_outline") or project.get("outline") or []):
        errors.append(f"section.section_id 不在已确认大纲中: {section_id}")
    if not title:
        errors.append("section.title 不能为空")
    if len(body) < 120:
        errors.append("section.body 必须是完整章节正文，长度至少 120 字符")
    if _contains_placeholder(body):
        errors.append("section.body 包含占位或待补充文案")
    if not isinstance(key_findings, list) or not any(_clean_text(item) for item in key_findings):
        errors.append("section.key_findings 至少需要 1 条非空关键发现")
    if not isinstance(evidence_chain, list) or not evidence_chain:
        errors.append("section.evidence_chain 至少需要 1 条证据链")
    else:
        for index, item in enumerate(evidence_chain, start=1):
            if not isinstance(item, dict):
                errors.append(f"section.evidence_chain[{index}] 必须是对象")
                continue
            if not _clean_text(item.get("claim")):
                errors.append(f"section.evidence_chain[{index}].claim 不能为空")
            if _contains_placeholder(_clean_text(item.get("claim"))):
                errors.append(f"section.evidence_chain[{index}].claim 包含占位文案")
            referenced_source_ids.update(
                _clean_text(source_id)
                for source_id in _ensure_list(item.get("source_ids"))
                if _clean_text(source_id)
            )
    if referenced_source_ids and not incoming_sources and not known_source_ids:
        errors.append("section.sources 必须包含 evidence_chain.source_ids 对应的来源详情")
    missing_source_ids = referenced_source_ids - known_source_ids
    if missing_source_ids:
        errors.append(
            "section.sources 缺少以下 source_id 的来源详情: "
            + ", ".join(sorted(missing_source_ids))
        )
    if isinstance(risks, list):
        for index, risk in enumerate(risks, start=1):
            if _contains_placeholder(_clean_text(risk)):
                errors.append(f"section.risks[{index}] 包含占位文案")
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
        "key_findings": [
            _clean_text(item) for item in _ensure_list(section.get("key_findings")) if _clean_text(item)
        ],
        "evidence_chain": [
            _normalize_evidence_item(item)
            for item in _ensure_list(section.get("evidence_chain"))
            if isinstance(item, dict)
        ],
        "sources": sources if sources is not None else _normalize_sources(section.get("sources")),
        "tables": [item for item in _ensure_list(section.get("tables")) if isinstance(item, dict)],
        "charts": [item for item in _ensure_list(section.get("charts")) if isinstance(item, dict)],
        "risks": [_clean_text(item) for item in _ensure_list(section.get("risks")) if _clean_text(item)],
    }


def _normalize_evidence_item(item: dict[str, Any]) -> dict[str, Any]:
    confidence = _clean_text(item.get("confidence")) or "medium"
    if confidence not in {"high", "medium", "low"}:
        confidence = "medium"
    return {
        "claim": _clean_text(item.get("claim")),
        "fact_ids": [_clean_text(value) for value in _ensure_list(item.get("fact_ids")) if _clean_text(value)],
        "source_ids": [
            _clean_text(value) for value in _ensure_list(item.get("source_ids")) if _clean_text(value)
        ],
        "confidence": confidence,
    }


async def _normalize_section_sources(
    project_id: str,
    section: dict[str, Any],
) -> list[dict[str, Any]]:
    incoming_sources = _normalize_sources(section.get("sources"))
    referenced_source_ids = _referenced_source_ids(section.get("evidence_chain"))
    if not referenced_source_ids:
        return incoming_sources

    sources_by_id = {
        source["source_id"]: source
        for source in incoming_sources
        if source.get("source_id")
    }
    missing_source_ids = referenced_source_ids - set(sources_by_id)
    if not missing_source_ids:
        return incoming_sources

    project = await research_project_repository.get_project(project_id=project_id)
    if not isinstance(project, dict):
        return incoming_sources
    existing_sources = _normalize_sources(project.get("sources"))
    for source in existing_sources:
        source_id = source.get("source_id")
        if source_id in missing_source_ids:
            sources_by_id[source_id] = source

    ordered_sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in [*incoming_sources, *existing_sources]:
        source_id = source.get("source_id")
        if not source_id or source_id not in sources_by_id or source_id in seen:
            continue
        seen.add(source_id)
        ordered_sources.append(sources_by_id[source_id])
    return ordered_sources


def _normalize_sources(value: Any) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for index, item in enumerate(_ensure_list(value), start=1):
        if not isinstance(item, dict):
            continue
        source_id = _clean_text(item.get("source_id")) or _clean_text(item.get("id")) or f"source-{index}"
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


def _referenced_source_ids(evidence_chain: Any) -> set[str]:
    source_ids: set[str] = set()
    for item in _ensure_list(evidence_chain):
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


def _clean_text(value: Any) -> str:
    return str(value or "").strip()
