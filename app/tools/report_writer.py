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
    "evidence_chain",
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
                "改写证据链",
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
                    "key_findings": ["str"],
                    "evidence_chain": [
                        {
                            "claim": "str",
                            "fact_ids": ["str"],
                            "source_ids": ["str"],
                            "confidence": "high | medium | low",
                        }
                    ],
                    "tables": ["dict"],
                    "charts": ["dict"],
                    "risks": ["str"],
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
    synthesis = research_result.get("synthesis") if isinstance(research_result.get("synthesis"), dict) else {}
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
    section_id = _normalize_text(str(section.get("section_id") or section.get("node_id") or index + 1))
    title = _normalize_text(str(section.get("title") or f"章节 {index + 1}"))
    body = str(section.get("body") or section.get("content") or section.get("description") or "").strip()
    return {
        "section_id": section_id,
        "title": title,
        "summary": _optional_text(section.get("summary")),
        "body": body or "本章节尚未提供正文内容。",
        "key_findings": [_normalize_text(str(item)) for item in _ensure_list(section.get("key_findings"))],
        "evidence_chain": [
            _normalize_evidence(item, evidence_index)
            for evidence_index, item in enumerate(_ensure_list(section.get("evidence_chain")))
            if isinstance(item, dict)
        ],
        "tables": [item for item in _ensure_list(section.get("tables")) if isinstance(item, dict)],
        "charts": [item for item in _ensure_list(section.get("charts")) if isinstance(item, dict)],
        "risks": [_normalize_text(str(item)) for item in _ensure_list(section.get("risks"))],
    }


def _normalize_evidence(evidence: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "claim": _normalize_text(str(evidence.get("claim") or f"证据链 {index + 1}")),
        "fact_ids": [str(item) for item in _ensure_list(evidence.get("fact_ids"))],
        "source_ids": [str(item) for item in _ensure_list(evidence.get("source_ids"))],
        "confidence": _normalize_text(str(evidence.get("confidence") or "medium")).lower(),
    }


def _normalize_source(source: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "source_id": _normalize_text(str(source.get("source_id") or source.get("id") or f"source-{index + 1}")),
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
        "evidence_chain": [],
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
                "evidence_chain": [],
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
                    "evidence_chain": [],
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
        f"<section class=\"report-section{' section-overview' if is_overview else ''}\" id=\"{anchor}\">",
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
        parts.append(_render_evidence_inline(section.get("evidence_chain", [])))
        parts.extend(_render_table(table, index) for index, table in enumerate(section.get("tables", [])))
        parts.extend(_render_chart_placeholder(chart, index) for index, chart in enumerate(section.get("charts", [])))
        parts.append(_render_risks(section.get("risks", [])))

    parts.append("</section>")
    return "".join(parts)


def _render_key_findings(findings: list[str]) -> str:
    if not findings:
        return ""
    items = "".join(f"<li>{escape(finding)}</li>" for finding in findings if finding)
    return f"<div class=\"finding-box\"><h3>关键发现</h3><ul>{items}</ul></div>"


def _render_evidence_chain(evidence_chain: list[dict[str, Any]]) -> str:
    """独立证据链框（保留给兼容场景）。"""
    if not evidence_chain:
        return ""
    rows = []
    for evidence in evidence_chain:
        source_refs = _build_citations(evidence["source_ids"])
        confidence = _confidence_label(evidence["confidence"])
        rows.append(
            "<li>"
            f"<span class=\"claim\">{escape(evidence['claim'])}</span>"
            f"<span class=\"confidence\">{escape(confidence)}</span>"
            f"{source_refs}"
            "</li>"
        )
    return "<div class=\"evidence-chain\"><h3>证据链</h3><ol>" + "".join(rows) + "</ol></div>"


def _render_evidence_inline(evidence_chain: list[dict[str, Any]]) -> str:
    """紧凑行内证据引用——叶子章节专用。

    合并同源引用，显示为一行：「来源：[1][2][3]」
    """
    if not evidence_chain:
        return ""
    all_source_ids: list[str] = []
    for evidence in evidence_chain:
        for sid in evidence.get("source_ids", []):
            if sid not in all_source_ids:
                all_source_ids.append(sid)
    if not all_source_ids:
        return ""
    citations = _build_citations(all_source_ids)
    return f"<p class=\"evidence-inline\"><span>证据来源：</span>{citations}</p>"


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
    description = _normalize_text(str(chart.get("description") or "主研究 agent 未提供可渲染图表数据。"))
    return (
        "<figure class=\"chart-placeholder\">"
        f"<figcaption>{escape(title)}</figcaption>"
        f"<p>{escape(description)}</p>"
        "</figure>"
    )


def _render_risks(risks: list[str]) -> str:
    if not risks:
        return ""
    items = "".join(f"<li>{escape(risk)}</li>" for risk in risks if risk)
    return f"<aside class=\"risk-notes\"><h3>不确定性与风险</h3><ul>{items}</ul></aside>"


def _render_references(
    sources: list[dict[str, Any]],
    sections: list[dict[str, Any]] | None = None,
) -> str:
    """渲染报告末尾的参考来源列表。

    输入为顶层 sources 数组和 sections 列表。
    当 sources 为空时，从所有 section 的 evidence_chain 中提取 source_ids，
    并用 evidence 的 claim 作为来源描述。每个来源条目带 id 锚点，供行内引用跳转。
    """
    parts = ["<section class=\"references\" id=\"references\"><h2>参考来源</h2><ol>"]

    if sources:
        for source in sources:
            source_id = escape(source.get("source_id", ""), quote=True)
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
    else:
        # 从 evidence_chain 自建来源列表（数据不完整时的兜底）
        evidence_sources = _collect_evidence_sources(sections or [])
        if not evidence_sources:
            parts.append("<li>暂无参考来源数据。</li>")
        else:
            for src in evidence_sources:
                parts.append(
                    f"<li id=\"ref-{escape(src['source_id'], quote=True)}\">"
                    f"{escape(src['title'])}</li>"
                )

    parts.append("</ol></section>")
    return "".join(parts)


def _collect_evidence_sources(
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """从所有 section 的 evidence_chain 中提取去重的来源信息。

    每个来源以 source_id 去重，取第一条 claim 作为标题。
    返回按 source_id 排序的列表。
    """
    seen: dict[str, dict[str, Any]] = {}
    for section in sections:
        for evidence in section.get("evidence_chain", []):
            for sid in evidence.get("source_ids", []):
                if not sid or sid in seen:
                    continue
                claim = evidence.get("claim", "")
                seen[sid] = {
                    "source_id": str(sid),
                    "title": claim if claim else f"来源 {str(sid).removeprefix('source-')}",
                }

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


def _public_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
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
  --bg: #f6f7f9;
  --paper: #ffffff;
  --ink: #1d2433;
  --muted: #667085;
  --line: #d9dee7;
  --accent: #246b5a;
  --accent-soft: #e3f1ed;
  --warn: #8a5a00;
  --warn-soft: #fff3cf;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans CJK SC", sans-serif;
  line-height: 1.72;
}
.report-paper {
  width: min(860px, calc(100% - 48px));
  margin: 40px auto 56px;
  background: var(--paper);
  border: 1px solid var(--line);
  padding: 56px 72px 48px;
}
.report-hero {
  padding-bottom: 32px;
  margin-bottom: 40px;
  border-bottom: 1px solid var(--line);
}
.eyebrow {
  color: var(--accent);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}
h1, h2, h3 { line-height: 1.28; letter-spacing: 0; }
h1 { margin: 10px 0 12px; font-size: 36px; }
h2 { margin: 0 0 16px; font-size: 25px; }
h3 { margin: 18px 0 10px; font-size: 18px; }
p { margin: 0 0 12px; }
a { color: var(--accent); }
.toc {
  padding-bottom: 20px;
  margin-bottom: 36px;
  border-bottom: 1px solid var(--line);
}
.summary-card {
  background: var(--accent-soft);
  border: 1px solid #c8e1da;
  padding: 24px 28px;
  margin-bottom: 40px;
}
.report-body {
  /* continuous flow — sections flow as one article */
}
.report-section {
  margin-bottom: 48px;
}
.report-section h2 {
  margin: 0 0 20px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}
.section-overview {
  border-left: 4px solid var(--accent);
  padding-left: 20px;
}
.references {
  margin-top: 48px;
  padding-top: 32px;
  border-top: 2px solid var(--line);
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
  padding: 4px 0 4px 18px;
  font-size: 14px;
  line-height: 1.6;
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
  padding: 4px 0;
  font-weight: 650;
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
}
.toc-tree a:hover {
  color: var(--accent);
  text-decoration: underline;
}
.section-summary {
  color: var(--muted);
  border-left: 3px solid var(--accent);
  padding-left: 12px;
}
.evidence-inline {
  color: var(--muted);
  font-size: 13px;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed var(--line);
}
.evidence-inline span {
  margin-right: 6px;
}
.finding-box, .evidence-chain, .chart-placeholder {
  background: var(--accent-soft);
  border: 1px solid #c8e1da;
  padding: 18px;
  margin: 18px 0;
}
.risk-notes {
  background: var(--warn-soft);
  border: 1px solid #f2d98a;
  color: var(--warn);
  padding: 14px 18px;
  margin: 18px 0;
}
.evidence-chain li {
  margin-bottom: 10px;
}
.claim {
  display: block;
  font-weight: 650;
}
.confidence {
  display: inline-block;
  margin-right: 8px;
  color: var(--muted);
  font-size: 13px;
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
.references li:target {
  background: var(--warn-soft);
  outline: 2px solid var(--warn);
  outline-offset: 2px;
}
.data-table {
  margin: 20px 0;
  overflow-x: auto;
}
figcaption {
  margin-bottom: 8px;
  color: var(--muted);
  font-weight: 650;
}
table {
  width: 100%;
  border-collapse: collapse;
  background: var(--paper);
}
th, td {
  border: 1px solid var(--line);
  padding: 10px 12px;
  text-align: left;
  vertical-align: top;
}
th {
  background: #eef2f6;
  font-weight: 700;
}
@media (max-width: 640px) {
  .report-paper { width: min(100% - 24px, 860px); padding: 32px 24px 24px; }
  h1 { font-size: 28px; }
  h2 { font-size: 22px; }
}
""".strip()
