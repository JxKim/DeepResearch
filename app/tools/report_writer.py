from html import escape
from typing import Any

from loguru import logger
from markdown_it import MarkdownIt

DEFAULT_TITLE = "研究报告"
SUPPORTED_BLOCK_TYPES = [
    "hero",
    "toc",
    "summary",
    "section",
    "key_findings",
    "table",
    "chart_placeholder",
    "risk_notes",
    "references",
]


async def get_report_render_schema() -> dict[str, Any]:
    """返回报告渲染工具支持的轻量展示契约。

    输入为空；输出为渲染调用方可参考的展示块说明。该 schema 只描述渲染层能力，
    不要求渲染阶段重新生成研究结论。
    """

    return {
        "purpose": "把主研究 agent 已完成的研究结果转换为可展示 HTML",
        "content_boundary": {
            "allowed": [
                "调整版式",
                "生成目录",
                "渲染引用脚注",
                "渲染表格",
                "渲染图表占位",
                "生成参考来源列表",
            ],
            "forbidden": [
                "新增事实",
                "新增来源",
                "新增结论",
                "改写事实引用",
                "调用搜索工具",
            ],
        },
        "research_result_shape": {
            "title": "str",
            "executive_summary": "str | None",
            "synthesis": {
                "executive_summary": "str | None",
                "core_conclusions": ["str"],
                "cross_section_insights": ["str"],
                "strategic_recommendations": ["str"],
                "global_risks": ["str"],
            },
            "sections": [
                {
                    "section_id": "str",
                    "title": "str",
                    "summary": "str | None",
                    "body": "str",
                    "key_findings": [
                        {
                            "finding_id": "str",
                            "claim": "str",
                            "source_ids": ["str"],
                            "confidence": "high | medium | low",
                        }
                    ],
                    "tables": ["dict"],
                    "charts": ["dict"],
                    "risks": [
                        {
                            "risk_id": "str",
                            "description": "str",
                            "source_ids": ["str"],
                            "risk_type": "str",
                            "severity": "high | medium | low",
                        }
                    ],
                }
            ],
            "sources": [
                {
                    "source_id": "str",
                    "title": "str",
                    "url": "str | None",
                    "published_at": "str | None",
                    "source_type": "str",
                }
            ],
        },
        "supported_block_types": SUPPORTED_BLOCK_TYPES,
    }


async def build_report_document(
    research_result: dict[str, Any],
    layout_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把主研究 agent 的研究结果转换为展示用 document IR。

    输入为完整研究结果和可选版式计划；输出为轻量 document IR。该函数只做结构化
    转换和字段归一化，不生成新的研究内容。
    """

    normalized_result = _normalize_research_result(research_result)
    layout = _normalize_layout_plan(layout_plan)
    document_ir = {
        "version": "deep-research-report-ir/v1",
        "title": normalized_result["title"],
        "subtitle": layout.get("subtitle"),
        "theme": layout.get("theme", "professional"),
        "executive_summary": normalized_result.get("executive_summary"),
        "sections": normalized_result["sections"],
        "sources": normalized_result["sources"],
    }
    logger.info(
        "报告展示 IR 已构建，title={}，sections={}，sources={}",
        document_ir["title"],
        len(document_ir["sections"]),
        len(document_ir["sources"]),
    )
    return document_ir


async def render_report_html(document_ir: dict[str, Any]) -> dict[str, Any]:
    """把 document IR 渲染成完整 HTML。

    输入为 build_report_document 生成的 document IR；输出为 title/html/sources。该函数
    负责 HTML 转义、目录、引用、参考来源和自包含样式。
    """

    document = _normalize_document_ir(document_ir)
    html = (
        "<!doctype html><html lang=\"zh-CN\"><head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{escape(document['title'])}</title>"
        f"<style>{_build_css()}</style>"
        "</head><body>"
        "<article class=\"report-paper\">"
        f"{_render_hero(document)}"
        f"{_render_toc(document['sections'])}"
        f"{_render_summary(document)}"
        "<div class=\"report-body\">"
        f"{''.join(_render_section(section) for section in document['sections'])}"
        "</div>"
        f"{_render_references(document['sources'], document['sections'])}"
        "</article>"
        "</body></html>"
    )
    logger.info("HTML 报告已渲染，title={}，chars={}", document["title"], len(html))
    return {
        "title": document["title"],
        "html": html,
        "sources": [_public_source(source) for source in document["sources"]],
    }


async def write_html_report(
    research_result: dict[str, Any] | None = None,
    layout_plan: dict[str, Any] | None = None,
    **legacy_kwargs: Any,
) -> dict[str, Any]:
    """最终报告渲染入口。

    输入为主研究 agent 产出的完整 research_result；输出为 title/html/sources。该工具
    只做展示转换和 HTML 渲染，不重写章节正文、不新增事实或来源。
    """

    if research_result is None:
        research_result = _build_research_result_from_legacy_kwargs(legacy_kwargs)
    document_ir = await build_report_document(
        research_result=research_result,
        layout_plan=layout_plan,
    )
    return await render_report_html(document_ir=document_ir)


def _normalize_research_result(research_result: dict[str, Any]) -> dict[str, Any]:
    title = _normalize_text(str(research_result.get("title") or DEFAULT_TITLE))
    synthesis = (
        research_result.get("synthesis")
        if isinstance(research_result.get("synthesis"), dict)
        else {}
    )
    executive_summary = (
        _optional_text(research_result.get("executive_summary"))
        or _optional_text(synthesis.get("executive_summary"))
    )
    sources = [
        _normalize_source(source, index)
        for index, source in enumerate(_ensure_list(research_result.get("sources")))
        if isinstance(source, dict)
    ]
    sections = [
        _normalize_section(section, index)
        for index, section in enumerate(_ensure_list(research_result.get("sections")))
        if isinstance(section, dict)
    ]
    if not sections:
        sections = [_fallback_section(research_result=research_result)]
    _apply_section_roles(sections)
    return {
        "title": title,
        "executive_summary": executive_summary,
        "sections": sections,
        "sources": sources,
    }


def _normalize_document_ir(document_ir: dict[str, Any]) -> dict[str, Any]:
    sections = [
        _normalize_section(section, index)
        for index, section in enumerate(_ensure_list(document_ir.get("sections")))
        if isinstance(section, dict)
    ]
    _apply_section_roles(sections)
    return {
        "title": _normalize_text(str(document_ir.get("title") or DEFAULT_TITLE)),
        "subtitle": _optional_text(document_ir.get("subtitle")),
        "theme": _normalize_text(str(document_ir.get("theme") or "professional")),
        "executive_summary": _optional_text(document_ir.get("executive_summary")),
        "sections": sections,
        "sources": [
            _normalize_source(source, index)
            for index, source in enumerate(_ensure_list(document_ir.get("sources")))
            if isinstance(source, dict)
        ],
    }


def _normalize_layout_plan(layout_plan: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(layout_plan, dict):
        return {}
    return {
        "subtitle": _optional_text(layout_plan.get("subtitle")),
        "theme": _normalize_text(str(layout_plan.get("theme") or "professional")),
    }


def _normalize_section(section: dict[str, Any], index: int) -> dict[str, Any]:
    section_id = _normalize_text(
        str(section.get("section_id") or section.get("node_id") or index + 1)
    )
    title = _normalize_text(str(section.get("title") or f"章节 {index + 1}"))
    body = str(
        section.get("body")
        or section.get("content")
        or section.get("description")
        or ""
    ).strip()
    return {
        "section_id": section_id,
        "title": title,
        "summary": _optional_text(section.get("summary")),
        "body": body or "本章节尚未提供正文内容。",
        "key_findings": _normalize_key_findings(section.get("key_findings")),
        "tables": [item for item in _ensure_list(section.get("tables")) if isinstance(item, dict)],
        "charts": [item for item in _ensure_list(section.get("charts")) if isinstance(item, dict)],
        "risks": _normalize_risks(section.get("risks")),
    }


def _normalize_key_findings(value: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, item in enumerate(_ensure_list(value), start=1):
        if isinstance(item, str):
            claim = _normalize_text(item)
            if claim:
                findings.append(
                    {
                        "finding_id": f"finding-{index}",
                        "claim": claim,
                        "source_ids": [],
                        "confidence": "medium",
                    }
                )
            continue
        if not isinstance(item, dict):
            continue
        claim = _normalize_text(
            str(item.get("claim") or item.get("summary") or item.get("title") or "")
        )
        if not claim:
            continue
        findings.append(
            {
                "finding_id": _normalize_text(str(item.get("finding_id") or f"finding-{index}")),
                "claim": claim,
                "source_ids": [str(value) for value in _ensure_list(item.get("source_ids"))],
                "confidence": _normalize_confidence(item.get("confidence")),
            }
        )
    return findings


def _normalize_risks(value: Any) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []
    for index, item in enumerate(_ensure_list(value), start=1):
        if isinstance(item, str):
            description = _normalize_text(item)
            if description:
                risks.append(
                    {
                        "risk_id": f"risk-{index}",
                        "description": description,
                        "source_ids": [],
                        "risk_type": "uncertainty",
                        "severity": "medium",
                    }
                )
            continue
        if not isinstance(item, dict):
            continue
        description = _normalize_text(
            str(item.get("description") or item.get("summary") or item.get("title") or "")
        )
        if not description:
            continue
        risks.append(
            {
                "risk_id": _normalize_text(str(item.get("risk_id") or f"risk-{index}")),
                "description": description,
                "source_ids": [str(value) for value in _ensure_list(item.get("source_ids"))],
                "risk_type": _normalize_text(str(item.get("risk_type") or "uncertainty")),
                "severity": _normalize_confidence(item.get("severity")),
            }
        )
    return risks


def _normalize_source(source: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "source_id": _normalize_text(
            str(source.get("source_id") or source.get("id") or f"source-{index + 1}")
        ),
        "title": _normalize_text(str(source.get("title") or f"来源 {index + 1}")),
        "url": source.get("url"),
        "published_at": source.get("published_at"),
        "source_type": _normalize_text(str(source.get("source_type") or "unknown")),
    }


def _fallback_section(research_result: dict[str, Any]) -> dict[str, Any]:
    body = _normalize_text(
        str(
            research_result.get("body")
            or research_result.get("executive_summary")
            or "当前研究结果未提供章节正文，无法渲染完整报告内容。"
        )
    )
    return {
        "section_id": "summary",
        "title": "研究内容",
        "summary": None,
        "body": body,
        "key_findings": [],
        "tables": [],
        "charts": [],
        "risks": [],
    }


def _build_research_result_from_legacy_kwargs(legacy_kwargs: dict[str, Any]) -> dict[str, Any]:
    title = _normalize_text(str(legacy_kwargs.get("title") or DEFAULT_TITLE))
    section_drafts = _ensure_list(legacy_kwargs.get("section_drafts"))
    sections: list[dict[str, Any]] = []
    for index, draft in enumerate(section_drafts):
        if not isinstance(draft, dict):
            continue
        sections.append(
            {
                "section_id": draft.get("section_id") or draft.get("id") or f"section-{index + 1}",
                "title": draft.get("title") or f"章节 {index + 1}",
                "body": draft.get("content") or "",
                "key_findings": [],
                "tables": [],
                "charts": [],
                "risks": [],
            }
        )
    if not sections:
        outline = _ensure_list(legacy_kwargs.get("outline"))
        for index, node in enumerate(outline):
            if not isinstance(node, dict):
                continue
            sections.append(
                {
                    "section_id": node.get("node_id") or f"section-{index + 1}",
                    "title": node.get("title") or f"章节 {index + 1}",
                    "summary": node.get("question"),
                    "body": node.get("description") or "",
                    "key_findings": [],
                    "tables": [],
                    "charts": [],
                    "risks": [],
                }
            )
    return {
        "title": title,
        "executive_summary": legacy_kwargs.get("executive_summary"),
        "sections": sections,
        "sources": legacy_kwargs.get("sources") or [],
    }


def _render_hero(document: dict[str, Any]) -> str:
    subtitle = document.get("subtitle") or "基于已确认研究结果生成"
    return (
        "<header class=\"report-hero\">"
        "<div class=\"eyebrow\">Deep Research Report</div>"
        f"<h1>{escape(document['title'])}</h1>"
        f"<p>{escape(str(subtitle))}</p>"
        "</header>"
    )


def _render_toc(sections: list[dict[str, Any]]) -> str:
    """渲染可折叠树形目录。

    将平铺 section 列表按 section_id 层级重建为树，父节点使用 <details> 实现折叠，
    叶子节点为普通 <li>。纯 HTML+CSS，无需 JavaScript。
    """
    if not sections:
        return ""
    tree = _build_toc_tree(sections)
    items = _render_toc_tree(tree)
    return "<nav class=\"toc\"><h2>目录</h2><ul class=\"toc-tree\">" + items + "</ul></nav>"


def _build_toc_tree(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将平铺的 section 列表构建为树形结构。

    每个节点包含: section_id, title, anchor, children (子节点列表)。
    父节点通过是否为其他 section_id 的前缀判断。
    """
    all_ids = {sec.get("section_id", "") for sec in sections}
    # 找出根节点：section_id 没有父前缀的
    roots: list[dict[str, Any]] = []
    node_map: dict[str, dict[str, Any]] = {}

    for sec in sections:
        sid = sec.get("section_id", "")
        node = {
            "section_id": sid,
            "title": sec.get("title", ""),
            "anchor": _section_anchor(sec),
            "children": [],
        }
        node_map[sid] = node

    for sid, node in node_map.items():
        # 找父节点：去掉最后一段 .N 前缀
        parent_id = _parent_section_id(sid, all_ids)
        if parent_id and parent_id in node_map:
            node_map[parent_id]["children"].append(node)
        else:
            roots.append(node)

    # 按 section_id 排序
    def _sort_key(n: dict[str, Any]) -> tuple:
        parts = n["section_id"].split(".")
        return tuple(int(p) if p.isdigit() else 0 for p in parts)

    roots.sort(key=_sort_key)
    for node in node_map.values():
        node["children"].sort(key=_sort_key)

    return roots


def _parent_section_id(section_id: str, all_ids: set[str]) -> str | None:
    """返回 section_id 的父节点 id，如 "2.2.1" → "2.2"，"2" → None。"""
    if "." not in section_id:
        return None
    parent = section_id.rsplit(".", 1)[0]
    while parent:
        if parent in all_ids:
            return parent
        if "." not in parent:
            return None
        parent = parent.rsplit(".", 1)[0]
    return None


def _render_toc_tree(nodes: list[dict[str, Any]], depth: int = 0) -> str:
    """递归渲染树形目录节点。

    有子节点的渲染为 <details><summary>，叶子节点为普通 <li>。
    """
    parts: list[str] = []
    for node in nodes:
        anchor = escape(node["anchor"], quote=True)
        sid = node.get("section_id", "")
        label = f"{sid} {node['title']}" if sid else node["title"]
        has_children = bool(node.get("children"))

        if has_children:
            parts.append("<li class=\"toc-parent\">")
            parts.append("<details open>")
            parts.append(f"<summary><a href=\"#{anchor}\">{escape(label)}</a></summary>")
            parts.append("<ul>")
            parts.append(_render_toc_tree(node["children"], depth + 1))
            parts.append("</ul>")
            parts.append("</details>")
            parts.append("</li>")
        else:
            parts.append(f"<li class=\"toc-leaf\"><a href=\"#{anchor}\">{escape(label)}</a></li>")
    return "".join(parts)


def _render_summary(document: dict[str, Any]) -> str:
    summary = document.get("executive_summary")
    if not summary:
        return ""
    return (
        "<section class=\"summary-card\" id=\"executive-summary\">"
        "<h2>核心摘要</h2>"
        f"{_render_paragraphs(str(summary))}"
        "</section>"
    )


def _apply_section_roles(sections: list[dict[str, Any]]) -> None:
    """为每个 section 设置 is_overview 标记（原地修改）。

    父章节（有其他 section_id 以该 id 为前缀）为概览型，只渲染正文；
    叶子章节为分析型，渲染完整结构。
    """
    parents = _compute_parent_sections(sections)
    for section in sections:
        section["is_overview"] = section.get("section_id", "") in parents


def _render_section(section: dict[str, Any]) -> str:
    """渲染单个章节为 HTML。

    概览型章节（is_overview=True）：只渲染标题、摘要和正文，不显示辅助框。
    分析型章节（叶子节点）：渲染标题、摘要、正文 + 关键发现/证据引用/风险。
    """
    is_overview = bool(section.get("is_overview"))
    anchor = escape(_section_anchor(section), quote=True)
    section_id = section.get("section_id", "")
    heading_text = f"{section_id} {section['title']}" if section_id else section["title"]
    parts = [
        (
            "<section class=\"report-section"
            f"{' section-overview' if is_overview else ''}\" id=\"{anchor}\">"
        ),
        f"<h2>{escape(heading_text)}</h2>",
    ]
    if section.get("summary"):
        parts.append(f"<p class=\"section-summary\">{escape(str(section['summary']))}</p>")
    body_text = str(section.get("body", ""))
    body_text = _strip_leading_heading(body_text)
    if is_overview:
        body_text = _truncate_at_first_subheading(body_text)
    parts.append(_render_body_markdown(body_text))

    if not is_overview:
        # 叶子章节：渲染辅助结构
        parts.append(_render_key_findings(section.get("key_findings", [])))
        parts.append(_render_source_refs_inline(section))
        parts.extend(
            _render_table(table, index)
            for index, table in enumerate(section.get("tables", []))
        )
        parts.extend(
            _render_chart_placeholder(chart, index)
            for index, chart in enumerate(section.get("charts", []))
        )
        parts.append(_render_risks(section.get("risks", [])))

    parts.append("</section>")
    return "".join(parts)


def _render_key_findings(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return ""
    items = []
    for finding in findings:
        claim = str(finding.get("claim") or "")
        if not claim:
            continue
        citations = _build_citations([str(value) for value in finding.get("source_ids", [])])
        confidence = _confidence_label(str(finding.get("confidence") or "medium"))
        items.append(
            "<li>"
            f"{escape(claim)}"
            f"{citations}"
            f"<span class=\"confidence\">{escape(confidence)}</span>"
            "</li>"
        )
    if not items:
        return ""
    items_html = "".join(items)
    return f"<div class=\"finding-box\"><h3>关键发现</h3><ul>{items_html}</ul></div>"


def _render_source_refs_inline(section: dict[str, Any]) -> str:
    """从关键发现和风险中渲染本章来源引用。"""

    all_source_ids = _collect_section_source_ids(section)
    if not all_source_ids:
        return ""
    citations = _build_citations(all_source_ids)
    return f"<p class=\"evidence-inline\"><span>证据来源：</span>{citations}</p>"


def _collect_section_source_ids(section: dict[str, Any]) -> list[str]:
    source_ids: list[str] = []
    for field_name in ("key_findings", "risks"):
        for item in section.get(field_name, []):
            if not isinstance(item, dict):
                continue
            for source_id in item.get("source_ids", []):
                normalized_source_id = _normalize_text(str(source_id))
                if normalized_source_id and normalized_source_id not in source_ids:
                    source_ids.append(normalized_source_id)
    return source_ids


def _render_table(table: dict[str, Any], index: int) -> str:
    title = _normalize_text(str(table.get("title") or f"表 {index + 1}"))
    headers = [str(item) for item in _ensure_list(table.get("headers"))]
    rows = [row for row in _ensure_list(table.get("rows")) if isinstance(row, list)]
    if not headers or not rows:
        return ""
    header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        "<figure class=\"data-table\">"
        f"<figcaption>{escape(title)}</figcaption>"
        f"<table><thead><tr>{header_html}</tr></thead><tbody>{body_html}</tbody></table>"
        "</figure>"
    )


def _render_chart_placeholder(chart: dict[str, Any], index: int) -> str:
    title = _normalize_text(str(chart.get("title") or f"图表 {index + 1}"))
    description = _normalize_text(
        str(chart.get("description") or "主研究 agent 未提供可渲染图表数据。")
    )
    return (
        "<figure class=\"chart-placeholder\">"
        f"<figcaption>{escape(title)}</figcaption>"
        f"<p>{escape(description)}</p>"
        "</figure>"
    )


def _render_risks(risks: list[dict[str, Any]]) -> str:
    if not risks:
        return ""
    items = []
    for risk in risks:
        description = str(risk.get("description") or "")
        if not description:
            continue
        citations = _build_citations([str(value) for value in risk.get("source_ids", [])])
        severity = _confidence_label(str(risk.get("severity") or "medium"))
        risk_type = str(risk.get("risk_type") or "uncertainty")
        items.append(
            "<li>"
            f"{escape(description)}"
            f"{citations}"
            f"<span class=\"confidence\">{escape(risk_type)} / {escape(severity)}</span>"
            "</li>"
        )
    if not items:
        return ""
    items_html = "".join(items)
    return f"<aside class=\"risk-notes\"><h3>不确定性与风险</h3><ul>{items_html}</ul></aside>"


def _render_references(
    sources: list[dict[str, Any]],
    sections: list[dict[str, Any]] | None = None,
) -> str:
    """渲染报告末尾的参考来源列表。

    输入为顶层 sources 数组和 sections 列表。每个来源条目带 id 锚点，供行内引用
    跳转；如果章节引用的 source_id 缺少来源详情，则保留明确的缺失说明。
    """
    parts = ["<section class=\"references\" id=\"references\"><h2>参考来源</h2><ol>"]
    rendered_source_ids: set[str] = set()

    for source in sources:
        raw_source_id = str(source.get("source_id") or "")
        if not raw_source_id:
            continue
        rendered_source_ids.add(raw_source_id)
        source_id = escape(raw_source_id, quote=True)
        source_text = escape(str(source.get("title", "")))
        if source.get("published_at"):
            source_text += f"，{escape(str(source['published_at']))}"
        if source.get("url"):
            source_text += (
                f"，<a href=\"{escape(str(source['url']), quote=True)}\""
                f" target=\"_blank\" rel=\"noopener\">"
                f"{escape(str(source['url']))}</a>"
            )
        parts.append(f"<li id=\"ref-{source_id}\">{source_text}</li>")

    referenced_sources = _collect_referenced_sources(sections or [])
    for source in referenced_sources:
        source_id = str(source["source_id"])
        if source_id in rendered_source_ids:
            continue
        rendered_source_ids.add(source_id)
        escaped_source_id = escape(source_id)
        parts.append(
            f"<li id=\"ref-{escape(source_id, quote=True)}\" class=\"reference-missing\">"
            f"来源详情缺失（{escaped_source_id}）</li>"
        )

    if not rendered_source_ids:
        parts.append("<li>暂无参考来源数据。</li>")

    parts.append("</ol></section>")
    return "".join(parts)


def _collect_referenced_sources(
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """在缺少来源详情时，从章节引用编号生成兜底来源列表。

    正常报告应使用 research_result.sources；该函数只处理 sources 为空的兼容渲染。
    """

    seen: dict[str, dict[str, Any]] = {}
    for section in sections:
        for finding in section.get("key_findings", []):
            _collect_source_ids_from_item(
                item=finding,
                title=str(finding.get("claim") or ""),
                seen=seen,
            )
        for risk in section.get("risks", []):
            _collect_source_ids_from_item(
                item=risk,
                title=str(risk.get("description") or ""),
                seen=seen,
            )

    def _sort_key(item: dict[str, Any]) -> tuple:
        sid = str(item.get("source_id", ""))
        parts = sid.removeprefix("source-").removeprefix("source_search-").split("-")
        nums = []
        for p in parts:
            try:
                nums.append(int(p))
            except ValueError:
                nums.append(9999)
        return tuple(nums) if nums else (9999,)

    return sorted(seen.values(), key=_sort_key)


def _collect_source_ids_from_item(
    item: dict[str, Any],
    title: str,
    seen: dict[str, dict[str, Any]],
) -> None:
    for sid in item.get("source_ids", []):
        source_id = str(sid or "")
        if not source_id or source_id in seen:
            continue
        seen[source_id] = {
            "source_id": source_id,
            "title": title if title else f"来源 {source_id.removeprefix('source-')}",
        }


_md_parser = MarkdownIt("commonmark", {"typographer": True}).enable(["table", "strikethrough"])


def _strip_leading_heading(body: str) -> str:
    """移除 body 开头第一个 Markdown 标题行，避免与 section 元数据的 h2 重复。

    输入为原始 Markdown body；输出为去掉首行 `## ...` / `### ...` 等标题后的文本。
    匹配任意层级的 ATX 标题（`# ` 到 `###### `），支持可选闭合 `##`。
    只移除首行标题，body 内部后续标题保留不动。
    """
    import re

    stripped = body.lstrip("\n")
    match = re.match(r"^#{1,6}\s+.+?(?:\s+#{1,6})?\s*\n", stripped)
    if match:
        return stripped[match.end():].lstrip("\n")
    return stripped


def _truncate_at_first_subheading(body: str) -> str:
    """在第一个子标题处截断 body，仅保留引言段落。

    父章节（overview）的 body 通常包含对每个子章节的摘要
    （如 ### 2.1 ...、### 2.2 ...），这些内容会被叶子章节重复渲染。
    该函数在 body 内第一个 `### ` 或 `## ` 处截断，只保留引言。
    如果 body 内没有子标题，则返回完整 body。
    """
    import re

    match = re.search(r"\n(?:#{2,6})\s+", body)
    if match:
        return body[: match.start()].strip()
    return body


def _render_body_markdown(text: str) -> str:
    """把 Markdown 正文渲染为 HTML 片段。

    输入为 sections[].body 的 Markdown 文本；输出为包含 h2/h3/p/ul/ol/strong/table
    等标签的 HTML 字符串。空输入返回占位提示。
    """
    stripped = text.strip()
    if not stripped:
        return "<p>本章节尚未提供正文内容。</p>"
    return _md_parser.render(stripped)


def _render_paragraphs(text: str) -> str:
    """兜底段落渲染器（保留向后兼容）。

    当 body 为非 Markdown 的纯文本时回退使用该函数；新渲染链路优先使用
    _render_body_markdown。
    """
    paragraphs = [item.strip() for item in str(text).split("\n") if item.strip()]
    if not paragraphs:
        paragraphs = ["本段暂无正文内容。"]
    return "".join(f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs)


def _build_citations(source_ids: list[str]) -> str:
    """生成可点击的来源引用角标，链接到参考来源列表。"""
    citations = []
    for source_id in source_ids:
        normalized_source_id = _normalize_text(str(source_id))
        if not normalized_source_id:
            continue
        label = normalized_source_id.removeprefix("source-")
        ref_id = escape(normalized_source_id, quote=True)
        citations.append(
            f"<a href=\"#ref-{ref_id}\" class=\"cite-link\">"
            f"<sup data-source-id=\"{ref_id}\">[{escape(label)}]</sup>"
            "</a>"
        )
    return "".join(citations)


def _section_anchor(section: dict[str, Any]) -> str:
    raw_id = _normalize_text(str(section.get("section_id") or section.get("title") or "section"))
    return "section-" + "".join(char if char.isalnum() or char in "-_" else "-" for char in raw_id)


def _confidence_label(confidence: str) -> str:
    labels = {"high": "高置信度", "medium": "中置信度", "low": "低置信度"}
    return labels.get(confidence, "中置信度")


def _normalize_confidence(value: Any) -> str:
    confidence = _normalize_text(str(value or "medium")).lower()
    return confidence if confidence in {"high", "medium", "low"} else "medium"


def _public_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": source.get("source_id"),
        "title": source["title"],
        "url": source.get("url"),
        "published_at": source.get("published_at"),
        "source_type": source["source_type"],
    }


def _ensure_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _normalize_text(str(value))
    return normalized or None


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split())


def _compute_parent_sections(sections: list[dict[str, Any]]) -> set[str]:
    """识别父章节（有其他 section 以其为前缀的节点）。

    输入为已归一化的 section 列表；输出为父章节 section_id 集合。
    例如 section_id "2" 是 "2.1" 的父节点，"2.2" 是 "2.2.1" 的父节点。
    """
    all_ids = {section.get("section_id", "") for section in sections}
    parents: set[str] = set()
    for sid in all_ids:
        if not sid:
            continue
        prefix = sid + "."
        if any(other.startswith(prefix) for other in all_ids if other != sid):
            parents.add(sid)
    return parents


def _build_css() -> str:
    return """
:root {
  color-scheme: light;
  --bg: #eef1ef;
  --paper: #ffffff;
  --ink: #202624;
  --muted: #65706b;
  --line: #dce2df;
  --line-strong: #bfc9c4;
  --accent: #176b5b;
  --accent-soft: #edf5f2;
  --warn: #8a5a16;
  --warn-soft: #fff8e8;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans CJK SC", sans-serif;
  font-size: 16px;
  line-height: 1.82;
}
.report-paper {
  width: min(940px, calc(100% - 48px));
  margin: 28px auto 48px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-top: 5px solid var(--accent);
  box-shadow: 0 16px 45px rgba(31, 44, 39, .08);
  padding: 64px 84px 56px;
}
.report-hero {
  padding-bottom: 36px;
  margin-bottom: 36px;
  border-bottom: 1px solid var(--line);
}
.eyebrow {
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}
h1, h2, h3 { line-height: 1.28; letter-spacing: 0; }
h1 {
  margin: 12px 0 16px;
  max-width: 20em;
  font-size: 38px;
  font-weight: 760;
  overflow-wrap: anywhere;
}
h2 { margin: 0 0 18px; font-size: 25px; font-weight: 720; }
h3 { margin: 28px 0 12px; font-size: 18px; font-weight: 700; }
h4 { margin: 24px 0 10px; font-size: 16px; }
p { margin: 0 0 16px; }
ul, ol { margin: 0 0 18px; padding-left: 1.45em; }
li { margin-bottom: 7px; }
strong { font-weight: 700; }
a { color: var(--accent); }
.report-hero p {
  max-width: 52em;
  margin: 0;
  color: var(--muted);
  font-size: 15px;
}
.toc {
  margin: 0 0 40px;
  padding: 24px 28px;
  background: #f6f8f7;
  border: 1px solid var(--line);
  border-left: 4px solid var(--line-strong);
}
.toc h2 { margin-bottom: 12px; font-size: 18px; }
.summary-card {
  background: var(--accent-soft);
  border-top: 1px solid #c8ddd6;
  border-bottom: 1px solid #c8ddd6;
  padding: 28px 30px 24px;
  margin: 0 0 48px;
}
.summary-card h2 { font-size: 20px; }
.summary-card p:last-child { margin-bottom: 0; }
.report-section {
  margin-bottom: 56px;
  scroll-margin-top: 24px;
}
.report-section h2 {
  margin: 0 0 24px;
  padding: 0 0 12px;
  border-bottom: 2px solid var(--ink);
}
.section-overview {
  margin-top: 8px;
  padding-left: 22px;
  border-left: 4px solid var(--accent);
}
.section-overview h2 {
  border-bottom-color: var(--line);
}
.references {
  margin-top: 64px;
  padding-top: 36px;
  border-top: 3px solid var(--ink);
  scroll-margin-top: 24px;
}
.references ol {
  padding-left: 1.6em;
}
.references li {
  margin-bottom: 12px;
  padding-left: 4px;
  color: #39423e;
  font-size: 14px;
  overflow-wrap: anywhere;
}
.references li.reference-missing {
  color: var(--warn);
  background: var(--warn-soft);
}
.references a {
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
}
.toc ul, .toc-tree {
  margin: 0;
  padding: 0;
  list-style: none;
}
.toc-tree ul {
  padding-left: 20px;
}
.toc-tree li {
  position: relative;
  margin: 0;
  padding: 3px 0 3px 18px;
  font-size: 14px;
  line-height: 1.65;
}
.toc-tree li::before {
  content: "";
  position: absolute;
  left: 4px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--line);
}
.toc-tree li:last-child::before {
  height: 12px;
}
.toc-parent > details > summary {
  position: relative;
  cursor: pointer;
  list-style: none;
  padding: 3px 0;
  font-weight: 700;
}
.toc-parent > details > summary::-webkit-details-marker {
  display: none;
}
.toc-parent > details > summary::before {
  content: "▾";
  position: absolute;
  left: -16px;
  top: 3px;
  font-size: 11px;
  color: var(--muted);
  transition: transform .15s;
}
.toc-parent > details[open] > summary::before {
  transform: rotate(-90deg);
}
.toc-leaf {
  position: relative;
}
.toc-leaf::after {
  content: "";
  position: absolute;
  left: 4px;
  top: 12px;
  width: 10px;
  height: 1px;
  background: var(--line);
}
.toc-tree a {
  color: var(--ink);
  text-decoration: none;
  overflow-wrap: anywhere;
}
.toc-tree a:hover {
  color: var(--accent);
}
.section-summary {
  margin: -8px 0 24px;
  padding: 12px 0 12px 16px;
  color: var(--muted);
  border-left: 3px solid var(--line-strong);
  font-size: 15px;
}
.evidence-inline {
  margin: 16px 0 24px;
  padding-top: 10px;
  border-top: 1px dashed var(--line);
  color: var(--muted);
  font-size: 13px;
}
.evidence-inline span {
  margin-right: 6px;
}
.finding-box {
  margin: 28px 0 20px;
  padding: 20px 24px 16px;
  background: var(--accent-soft);
  border-left: 4px solid var(--accent);
}
.finding-box h3 {
  margin: 0 0 12px;
  color: var(--accent);
  font-size: 16px;
}
.finding-box ul {
  margin-bottom: 0;
}
.finding-box li {
  margin-bottom: 12px;
  padding-left: 3px;
}
.finding-box li:last-child {
  margin-bottom: 0;
}
.chart-placeholder {
  margin: 24px 0;
  padding: 20px 24px;
  background: #f6f8f7;
  border: 1px dashed var(--line-strong);
}
.risk-notes {
  margin: 28px 0 20px;
  padding: 18px 24px 14px;
  background: var(--warn-soft);
  border-left: 4px solid #c58a2a;
  color: var(--warn);
}
.risk-notes h3 {
  margin: 0 0 10px;
  font-size: 16px;
}
.risk-notes ul {
  margin-bottom: 0;
}
.claim {
  display: block;
  font-weight: 700;
}
.confidence {
  display: block;
  margin-top: 3px;
  color: var(--muted);
  font-size: 12px;
}
.cite-link {
  text-decoration: none;
}
.cite-link sup {
  margin-left: 4px;
  color: var(--accent);
  font-weight: 700;
}
.cite-link:hover sup {
  color: var(--ink);
  text-decoration: underline;
}
.references li:target,
.references li.report-anchor-highlight {
  background: var(--warn-soft);
  outline: 2px solid #d19a3f;
  outline-offset: 3px;
}
.data-table {
  margin: 28px 0;
  overflow-x: auto;
  border: 1px solid var(--line);
}
figcaption {
  padding: 9px 12px;
  background: #f6f8f7;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
  font-size: 13px;
  font-weight: 700;
}
table {
  width: 100%;
  border-collapse: collapse;
  background: var(--paper);
  font-size: 14px;
}
th, td {
  padding: 11px 13px;
  border-right: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
tr:last-child td { border-bottom: 0; }
th:last-child, td:last-child { border-right: 0; }
th {
  background: #eef2f0;
  font-weight: 700;
}
tbody tr:nth-child(even) { background: #fafbfa; }
blockquote {
  margin: 24px 0;
  padding: 4px 0 4px 18px;
  border-left: 3px solid var(--line-strong);
  color: var(--muted);
}
code {
  padding: 2px 5px;
  background: #eef2f0;
  border-radius: 3px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .9em;
}
pre {
  max-width: 100%;
  margin: 24px 0;
  padding: 18px;
  overflow-x: auto;
  background: #202624;
  color: #f3f5f4;
}
pre code {
  padding: 0;
  background: transparent;
  color: inherit;
}
@media (max-width: 720px) {
  body { background: var(--paper); font-size: 15px; }
  .report-paper {
    width: 100%;
    margin: 0;
    padding: 34px 22px 40px;
    border: 0;
    border-top: 4px solid var(--accent);
    box-shadow: none;
  }
  .report-hero { margin-bottom: 28px; padding-bottom: 28px; }
  h1 { font-size: 29px; }
  h2 { font-size: 21px; }
  .toc { padding: 20px; }
  .summary-card { margin-left: -22px; margin-right: -22px; padding: 24px 22px 20px; }
  .report-section { margin-bottom: 44px; }
  .section-overview { padding-left: 16px; }
  .finding-box, .risk-notes { padding-left: 18px; padding-right: 18px; }
  th, td { min-width: 120px; }
}
@media print {
  body { background: #fff; }
  .report-paper {
    width: 100%;
    margin: 0;
    padding: 0;
    border: 0;
    box-shadow: none;
  }
  .toc { break-after: page; }
  .report-section, .finding-box, .risk-notes, .data-table { break-inside: avoid; }
  a { color: inherit; text-decoration: none; }
}
""".strip()
