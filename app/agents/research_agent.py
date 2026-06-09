import json
from collections.abc import Callable
from datetime import date, datetime
from inspect import isawaitable
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.utils import create_file_data
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger
from pydantic import BaseModel, Field

from app.config.config import Settings, get_settings
from app.repository import research_project_repository
from app.schemas import OutlineNode, ReportSource
from app.tools.external_search import external_search
from app.tools.ragflow_search import ragflow_search
from app.tools.report_writer import write_html_report
from app.tools.research_workspace import save_research_section
from app.tools.web_reader import read_web_page

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
RESEARCH_MANAGER_PROMPT_PATH = PROMPT_DIR / "research_manager.md"
SEARCH_AGENT_PROMPT_PATH = PROMPT_DIR / "search_agent.md"


class ResearchBrief(BaseModel):
    """研究任务书结构。

    输入来自研究项目设定和研究管理智能体输出；输出用于保存本次研究的目标、边界、
    默认假设和交付标准。该结构不保存报告正文。
    """

    topic: str
    research_goal: str
    target_audience: str
    scope_summary: str
    key_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class FactCard(BaseModel):
    """事实卡片结构。

    输入来自信息检索智能体整理后的证据；输出用于报告生成和事实追溯。该结构只保存
    可复核事实和来源编号，不保存大段原文。
    """

    fact_id: str
    statement: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class InsightCard(BaseModel):
    """洞察卡片结构。

    输入来自研究管理智能体对事实卡片的归纳；输出用于报告生成。该结构表达判断和
    推理链条，不直接执行检索。
    """

    insight_id: str
    title: str
    summary: str
    supporting_fact_ids: list[str] = Field(default_factory=list)


class ResearchSynthesis(BaseModel):
    """全局研究综合结构。

    输入来自所有章节研究结果的聚合；输出给确定性报告渲染流程构建首页摘要、核心结论、
    跨章节洞察、建议和全局风险。该结构不承担新增事实，只汇总已落库章节内容。
    """

    executive_summary: str | None = None
    core_conclusions: list[str] = Field(default_factory=list)
    cross_section_insights: list[str] = Field(default_factory=list)
    strategic_recommendations: list[str] = Field(default_factory=list)
    global_risks: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """章节证据链条。

    输入来自主研究智能体已经完成的研究过程；输出给确定性渲染流程展示引用和
    置信度。该结构不允许报告渲染阶段新增或改写。
    """

    claim: str
    fact_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class ResearchSection(BaseModel):
    """研究报告章节内容。

    输入来自主研究智能体落库的研究结果；输出给确定性渲染流程做展示转换。章节正文、
    关键发现和证据链在研究阶段完成，渲染阶段只负责排版。
    """

    section_id: str
    title: str
    summary: str | None = None
    body: str
    key_findings: list[str] = Field(default_factory=list)
    evidence_chain: list[EvidenceItem] = Field(default_factory=list)
    sources: list[ReportSource] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ResearchResult(BaseModel):
    """完整研究结果。

    输入来自研究过程落库文件或项目记录；输出给确定性渲染流程生成 HTML。该结构
    是研究和报告渲染之间的边界对象。
    """

    title: str
    executive_summary: str | None = None
    sections: list[ResearchSection] = Field(default_factory=list)
    sources: list[ReportSource] = Field(default_factory=list)
    fact_cards: list[FactCard] = Field(default_factory=list)
    insight_cards: list[InsightCard] = Field(default_factory=list)
    synthesis: ResearchSynthesis | None = None


class ResearchBriefResult(BaseModel):
    """研究任务书和大纲生成结果。

    输入来自研究管理智能体输出；输出给 background 保存研究任务书和大纲草案。
    """

    research_brief: ResearchBrief
    outline: list[OutlineNode]


class ReportGenerationResult(BaseModel):
    """研究报告生成结果。

    输入来自研究管理智能体协调信息检索和报告生成后的输出；输出给 background 保存
    来源、事实卡片、洞察卡片和报告版本。
    """

    title: str
    html: str
    sources: list[ReportSource] = Field(default_factory=list)
    fact_cards: list[FactCard] = Field(default_factory=list)
    insight_cards: list[InsightCard] = Field(default_factory=list)


class ResearchAgent:
    """研究智能体业务门面。

    输入为 DeepAgents 研究管理智能体；输出为 background 可直接调用的三个业务方法。
    该类隔离研究准备、研究过程和确定性报告渲染的框架细节。
    """

    def __init__(self, manager_agent: Any | None = None, report_agent: Any | None = None) -> None:
        """初始化研究智能体门面。

        输入为可选的 DeepAgents 研究管理智能体；输出为空。manager_agent 负责研究
        准备、大纲和逐章节研究，报告渲染由确定性工具完成。
        """

        self.manager_agent = manager_agent
        self.report_agent = report_agent

    async def generate_research_brief(self, project: dict[str, Any] | None) -> ResearchBriefResult:
        """生成研究任务书和大纲草案。

        输入为研究项目文档；输出为研究任务书和大纲节点列表。该方法负责把项目数据
        转换为 DeepAgents 输入，并解析结构化输出。
        """

        payload = self._build_generate_research_brief_input(project=project)
        raw_result = await self._invoke_manager_agent(
            task_name="generate_research_brief",
            payload=payload,
        )
        result = self._parse_research_brief_result(raw_result=raw_result, project=project)
        logger.info("研究任务书和大纲结果已生成，topic={}", result.research_brief.topic)
        return result

    async def revise_outline(
        self,
        project: dict[str, Any] | None,
        outline: list[OutlineNode],
        revision_instruction: str,
    ) -> list[OutlineNode]:
        """根据用户要求修改研究大纲。

        输入为研究项目、当前大纲和用户修改要求；输出为修订后的大纲节点列表。该方法
        不保存结果，持久化由 background 和 repository 完成。
        """

        payload = self._build_revise_outline_input(
            project=project,
            outline=outline,
            revision_instruction=revision_instruction,
        )
        raw_result = await self._invoke_manager_agent(
            task_name="revise_outline",
            payload=payload,
        )
        revised_outline = self._parse_outline_result(
            raw_result=raw_result,
            fallback_outline=outline,
        )
        logger.info("研究大纲修订结果已生成，outline_nodes={}", len(revised_outline))
        return revised_outline

    async def generate_research_result(
        self,
        project: dict[str, Any] | None,
        outline: list[OutlineNode],
        user_instruction: str | None,
    ) -> ResearchResult:
        """执行研究过程并生成完整研究结果。

        输入为研究项目、已确认大纲和可选研究要求；输出为可落库的 ResearchResult。
        该方法通过 manager_agent 协调检索子智能体、整理事实和洞察、撰写章节正文，
        不生成 HTML。
        """

        project_id = self._get_project_id(project=project)
        await research_project_repository.clear_research_sections(project_id=project_id)
        expected_section_ids = self._expected_research_section_ids(outline=outline)
        sections: list[dict[str, Any]] = []
        missing_section_ids = sorted(expected_section_ids)
        for attempt in range(1, 5):
            payload = self._build_generate_research_result_input(
                project=project,
                outline=outline,
                user_instruction=user_instruction,
                required_section_ids=sorted(expected_section_ids),
                missing_section_ids=missing_section_ids,
                attempt=attempt,
            )
            await self._invoke_manager_agent(
                task_name="generate_report",
                payload=payload,
            )
            sections = await research_project_repository.get_research_sections(
                project_id=project_id
            )
            saved_section_ids = {
                str(section.get("section_id"))
                for section in sections
                if isinstance(section, dict) and section.get("section_id")
            }
            missing_section_ids = sorted(expected_section_ids - saved_section_ids)
            if not missing_section_ids:
                break
            logger.warning(
                "研究章节尚未写全，准备继续补写，project_id={}，attempt={}，missing={}",
                project_id,
                attempt,
                missing_section_ids,
            )
        result = self._build_research_result_from_saved_sections(
            sections=sections,
            sources=await research_project_repository.get_research_sources(project_id=project_id),
            project=project,
            outline=outline,
        )
        logger.info("完整研究结果已生成，title={}，sections={}", result.title, len(result.sections))
        return result

    def _get_project_id(self, project: dict[str, Any] | None) -> str:
        """从项目文档中提取 project_id，缺失时终止研究任务。"""

        project_id = (project or {}).get("project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("研究项目缺少 project_id，无法逐章节落库")
        return project_id

    async def generate_report(
        self,
        project: dict[str, Any] | None,
        outline: list[OutlineNode],
        user_instruction: str | None,
    ) -> ReportGenerationResult:
        """渲染 HTML 研究报告。

        输入为研究项目、已确认大纲和可选展示要求；输出为报告标题、HTML、来源、事实
        卡片和洞察卡片。
        """

        payload = self._build_generate_report_input(
            project=project,
            outline=outline,
            user_instruction=user_instruction,
        )
        raw_result = await write_html_report(
            research_result=payload["research_result"],
            layout_plan=self._build_default_layout_plan(payload=payload),
        )
        result = self._parse_report_generation_result(raw_result=raw_result, project=project)
        logger.info("研究报告结果已生成，title={}", result.title)
        return result

    def _build_generate_research_brief_input(
        self,
        project: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """构建研究任务书生成的 DeepAgents 输入。

        输入为项目文档；输出为框架无关的任务载荷。后续接入 DeepAgents 时，该载荷会在
        _invoke_manager_agent 中转换为具体 messages 或 state。
        """

        project_data = project or {}
        return {
            "task_name": "generate_research_brief",
            "project": project_data,
            "expected_output": "ResearchBriefResult",
        }

    def _build_revise_outline_input(
        self,
        project: dict[str, Any] | None,
        outline: list[OutlineNode],
        revision_instruction: str,
    ) -> dict[str, Any]:
        """构建大纲修订的 DeepAgents 输入。

        输入为项目文档、当前大纲和修改要求；输出为框架无关的任务载荷。
        """

        return {
            "task_name": "revise_outline",
            "project": project or {},
            "outline": [node.model_dump(mode="python") for node in outline],
            "revision_instruction": revision_instruction,
            "expected_output": "list[OutlineNode]",
        }

    def _build_generate_research_result_input(
        self,
        project: dict[str, Any] | None,
        outline: list[OutlineNode],
        user_instruction: str | None,
        required_section_ids: list[str] | None = None,
        missing_section_ids: list[str] | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        """构建研究执行输入。

        输入为项目文档、已确认大纲和可选研究要求；输出为 manager_agent 的任务载荷。
        虽然任务类型沿用 generate_report，但期望输出已经改为 research_result。
        """

        return {
            "task_name": "generate_report",
            "project": project or {},
            "outline": [node.model_dump(mode="python") for node in outline],
            "user_instruction": user_instruction,
            "expected_output": "save sections with save_research_section",
            "required_section_ids": required_section_ids or [],
            "missing_section_ids": missing_section_ids or [],
            "attempt": attempt,
        }

    def _build_generate_report_input(
        self,
        project: dict[str, Any] | None,
        outline: list[OutlineNode],
        user_instruction: str | None,
    ) -> dict[str, Any]:
        """构建报告渲染输入。

        输入为项目文档、已确认大纲和用户展示要求；输出为确定性渲染工具使用的任务
        载荷。research_result 优先来自项目落库记录，缺失时按大纲生成兜底结构。
        """

        project_data = project or {}
        research_result = self._build_research_result_from_project(
            project=project_data,
            outline=outline,
        )
        return {
            "task_name": "render_report",
            "project_id": project_data.get("project_id"),
            "research_result": research_result.model_dump(mode="python"),
            "user_instruction": user_instruction,
            "expected_output": "ReportGenerationResult",
        }

    def _build_default_layout_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        """构建报告渲染兜底版式计划。"""

        user_instruction = payload.get("user_instruction")
        return {
            "subtitle": user_instruction if isinstance(user_instruction, str) else None,
            "theme": "professional",
        }

    def _build_research_result_from_project(
        self,
        project: dict[str, Any],
        outline: list[OutlineNode],
    ) -> ResearchResult:
        """从项目落库记录构建研究结果边界对象。

        输入为 repository 返回的项目文档和已确认大纲；输出为确定性渲染工具可渲染的
        ResearchResult。后续研究过程如果落库 research_result，则优先使用落库版本。
        """

        stored_research_result = project.get("research_result")
        if isinstance(stored_research_result, dict):
            return ResearchResult.model_validate(stored_research_result)

        topic = str(project.get("topic") or "未命名研究主题")
        sources = [
            ReportSource.model_validate(source)
            for source in project.get("sources", [])
            if isinstance(source, dict)
        ]
        fact_cards = [
            FactCard.model_validate(card)
            for card in project.get("fact_cards", [])
            if isinstance(card, dict)
        ]
        insight_cards = [
            InsightCard.model_validate(card)
            for card in project.get("insight_cards", [])
            if isinstance(card, dict)
        ]
        sections = self._build_research_sections_from_project(
            project=project,
            outline=outline,
        )
        return ResearchResult(
            title=f"{topic}研究报告",
            executive_summary=self._build_executive_summary_from_project(project=project),
            sections=sections,
            sources=sources,
            fact_cards=fact_cards,
            insight_cards=insight_cards,
        )

    def _build_research_sections_from_project(
        self,
        project: dict[str, Any],
        outline: list[OutlineNode],
    ) -> list[ResearchSection]:
        """从项目落库章节或大纲构建研究章节。

        输入为项目文档和大纲；输出为 ResearchSection 列表。真实研究过程应落库完整
        sections；当前没有完整章节正文时，只生成明确的兜底章节，不让渲染阶段补写。
        """

        stored_sections = project.get("sections")
        if isinstance(stored_sections, list) and stored_sections:
            return [
                ResearchSection.model_validate(section)
                for section in stored_sections
                if isinstance(section, dict)
            ]

        if outline:
            return [
                ResearchSection(
                    section_id=node.node_id,
                    title=node.title,
                    summary=node.question,
                    body=node.description,
                    key_findings=[],
                    evidence_chain=[],
                    tables=[],
                    charts=[],
                    risks=[],
                )
                for node in outline
            ]

        return [
            ResearchSection(
                section_id="summary",
                title="研究内容",
                summary=None,
                body="当前研究过程尚未落库完整章节正文，确定性渲染流程不会自行补写研究内容。",
                key_findings=[],
                evidence_chain=[],
                tables=[],
                charts=[],
                risks=[],
            )
        ]

    def _build_research_result_from_saved_sections(
        self,
        sections: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        project: dict[str, Any] | None,
        outline: list[OutlineNode],
    ) -> ResearchResult:
        """从主研究智能体已落库章节组装 ResearchResult。"""

        project_data = project or {}
        expected_section_ids = self._expected_research_section_ids(outline=outline)
        saved_sections = [
            ResearchSection.model_validate(section)
            for section in sections
            if isinstance(section, dict)
        ]
        saved_section_ids = {section.section_id for section in saved_sections}
        missing_section_ids = sorted(expected_section_ids - saved_section_ids)
        if not saved_sections:
            raise ValueError("主研究智能体没有通过 save_research_section 保存任何章节")
        if missing_section_ids:
            raise ValueError(f"主研究智能体缺少章节研究结果: {', '.join(missing_section_ids)}")

        self._validate_saved_research_sections(saved_sections)
        topic = str(project_data.get("topic") or "未命名研究主题")
        saved_sources = self._collect_saved_sources(
            sources=sources,
            sections=sections,
        )
        fact_cards = self._build_fact_cards_from_sections(saved_sections)
        insight_cards = self._build_insight_cards_from_sections(saved_sections)
        synthesis = self._build_synthesis_from_sections(saved_sections)
        return ResearchResult(
            title=f"{topic}研究报告",
            executive_summary=synthesis.executive_summary,
            sections=saved_sections,
            sources=saved_sources,
            fact_cards=fact_cards,
            insight_cards=insight_cards,
            synthesis=synthesis,
        )

    def _collect_saved_sources(
        self,
        sources: list[dict[str, Any]],
        sections: list[dict[str, Any]],
    ) -> list[ReportSource]:
        """从项目级来源和章节级来源中去重组装 ReportSource。"""

        collected: dict[str, ReportSource] = {}
        for source in [*sources, *self._extract_sources_from_sections(sections)]:
            if not isinstance(source, dict):
                continue
            try:
                report_source = ReportSource.model_validate(source)
            except Exception:
                continue
            key = (
                report_source.source_id
                or report_source.url
                or f"{report_source.source_type}:{report_source.title}"
            )
            collected[key] = report_source
        return list(collected.values())

    def _extract_sources_from_sections(self, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
        section_sources: list[dict[str, Any]] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            for source in section.get("sources") or []:
                if isinstance(source, dict):
                    section_sources.append(source)
        return section_sources

    def _expected_research_section_ids(self, outline: list[OutlineNode]) -> set[str]:
        """计算需要落库正文的章节节点。优先使用叶子节点；没有叶子时使用顶层节点。"""

        leaf_ids: set[str] = set()
        all_ids: set[str] = set()
        for node in outline:
            self._collect_outline_node_ids(node=node, all_ids=all_ids, leaf_ids=leaf_ids)
        return leaf_ids or all_ids

    def _collect_outline_node_ids(
        self,
        node: OutlineNode,
        all_ids: set[str],
        leaf_ids: set[str],
    ) -> None:
        all_ids.add(node.node_id)
        if not node.children:
            leaf_ids.add(node.node_id)
            return
        for child in node.children:
            self._collect_outline_node_ids(node=child, all_ids=all_ids, leaf_ids=leaf_ids)

    def _validate_saved_research_sections(self, sections: list[ResearchSection]) -> None:
        """阻止占位章节进入报告渲染阶段。"""

        placeholder_markers = ["占位", "待生成", "待补充", "真实内容将在", "尚未接入真实"]
        for section in sections:
            section_text = " ".join(
                [
                    section.body,
                    " ".join(section.key_findings),
                    " ".join(item.claim for item in section.evidence_chain),
                    " ".join(section.risks),
                ]
            )
            if any(marker in section_text for marker in placeholder_markers):
                raise ValueError(f"章节 {section.section_id} 包含占位内容")
            if not section.body.strip():
                raise ValueError(f"章节 {section.section_id} 缺少正文")
            if not section.key_findings:
                raise ValueError(f"章节 {section.section_id} 缺少关键发现")
            if not section.evidence_chain:
                raise ValueError(f"章节 {section.section_id} 缺少证据链")
            section_source_ids = {source.source_id for source in section.sources if source.source_id}
            evidence_source_ids = {
                source_id
                for item in section.evidence_chain
                for source_id in item.source_ids
                if source_id
            }
            missing_source_ids = evidence_source_ids - section_source_ids
            if missing_source_ids:
                raise ValueError(
                    f"章节 {section.section_id} 缺少来源详情: {', '.join(sorted(missing_source_ids))}"
                )

    def _build_fact_cards_from_sections(self, sections: list[ResearchSection]) -> list[FactCard]:
        """从章节证据链确定性聚合事实卡片。"""

        cards: dict[str, FactCard] = {}
        for section in sections:
            for index, evidence in enumerate(section.evidence_chain, start=1):
                fact_ids = evidence.fact_ids or [f"fact-{section.section_id}-{index}"]
                for fact_id in fact_ids:
                    cards[fact_id] = FactCard(
                        fact_id=fact_id,
                        statement=evidence.claim,
                        source_ids=evidence.source_ids,
                        confidence=evidence.confidence,
                    )
        return list(cards.values())

    def _build_insight_cards_from_sections(self, sections: list[ResearchSection]) -> list[InsightCard]:
        """从章节摘要和关键发现确定性聚合洞察卡片。"""

        cards: list[InsightCard] = []
        for section in sections:
            summary = section.summary or (section.key_findings[0] if section.key_findings else "")
            if not summary:
                continue
            supporting_fact_ids = [
                fact_id
                for evidence in section.evidence_chain
                for fact_id in evidence.fact_ids
                if fact_id
            ]
            cards.append(
                InsightCard(
                    insight_id=f"insight-{section.section_id}",
                    title=section.title,
                    summary=summary,
                    supporting_fact_ids=supporting_fact_ids,
                )
            )
        return cards

    def _build_synthesis_from_sections(self, sections: list[ResearchSection]) -> ResearchSynthesis:
        """从已完成章节确定性生成全局研究综合。"""

        core_conclusions: list[str] = []
        cross_section_insights: list[str] = []
        strategic_recommendations: list[str] = []
        global_risks: list[str] = []
        for section in sections:
            if section.summary:
                core_conclusions.append(section.summary)
            core_conclusions.extend(section.key_findings[:2])
            cross_section_insights.append(f"{section.title}: {section.summary or section.key_findings[0]}")
            global_risks.extend(section.risks[:2])

        unique_conclusions = self._dedupe_texts(core_conclusions)[:8]
        unique_insights = self._dedupe_texts(cross_section_insights)[:8]
        unique_risks = self._dedupe_texts(global_risks)[:8]
        if unique_conclusions:
            executive_summary = "；".join(unique_conclusions[:6])
        else:
            executive_summary = "本报告基于已确认大纲逐章节完成研究。"
        return ResearchSynthesis(
            executive_summary=executive_summary,
            core_conclusions=unique_conclusions,
            cross_section_insights=unique_insights,
            strategic_recommendations=strategic_recommendations,
            global_risks=unique_risks,
        )

    def _dedupe_texts(self, values: list[str]) -> list[str]:
        """按原顺序去重文本列表。"""

        seen: set[str] = set()
        deduped: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
        return deduped

    def _build_executive_summary_from_sections(self, sections: list[ResearchSection]) -> str:
        findings: list[str] = []
        for section in sections:
            findings.extend(section.key_findings[:2])
            if len(findings) >= 6:
                break
        return "；".join(findings[:6]) if findings else "本报告基于已确认大纲逐章节完成研究。"

    def _build_executive_summary_from_project(self, project: dict[str, Any]) -> str | None:
        """从项目落库记录提取研究摘要。"""

        research_brief = project.get("research_brief")
        if not isinstance(research_brief, dict):
            return None
        scope_summary = research_brief.get("scope_summary")
        if isinstance(scope_summary, str) and scope_summary.strip():
            return scope_summary
        return None

    async def _invoke_manager_agent(self, task_name: str, payload: dict[str, Any]) -> Any:
        """调用研究管理智能体。

        输入为任务名称和任务载荷；输出为 DeepAgents 原始结果。manager_agent 为空时
        返回占位结果；真实 DeepAgents 调用会注入 thread_id 和虚拟文件系统初始文件。
        """

        if self.manager_agent is None:
            logger.warning("研究管理智能体尚未接入，使用占位结果，task_name={}", task_name)
            return self._build_placeholder_result(task_name=task_name, payload=payload)

        return await self.manager_agent.ainvoke(
            self._build_deepagents_input(payload=payload),
            config=self._build_deepagents_config(payload=payload)
        )

    def _build_deepagents_input(self, payload: dict[str, Any]) -> dict[str, Any]:
        """构建 DeepAgents 运行输入。

        输入为业务任务载荷，输出为 DeepAgents state。大 payload 写入虚拟文件系统，
        messages 中只保留任务说明和文件路径，减少主上下文膨胀。
        """

        task_json = json.dumps(payload, ensure_ascii=False, indent=2, default=self._json_default)
        return {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "请执行 /research/task_payload.json 中的研究任务。"
                        "先使用 todo 规划步骤；大规模检索结果和报告中间稿请写入"
                        " /research/workspace/ 下的文件；最终只返回严格 JSON。"
                    ),
                }
            ],
            "files": {
                "/research/task_payload.json": create_file_data(task_json),
                "/research/workspace/README.md": create_file_data(
                    "该目录用于保存检索摘要、来源整理、事实卡片、洞察卡片和报告草稿。"
                ),
            },
        }

    def _build_deepagents_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """构建 DeepAgents 运行配置。

        输入为业务任务载荷，输出为包含 thread_id 的 LangGraph config。thread_id 以项目
        编号为主，保证同一研究项目的短期文件系统和 checkpoint 能被复用。
        """

        project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
        project_id = project.get("project_id") or payload.get("project_id") or "default-project"
        task_name = payload.get("task_name") or "research-task"
        return {"configurable": {"thread_id": f"research:{project_id}:{task_name}"}}

    @staticmethod
    def _json_default(value: Any) -> str:
        """序列化 MongoDB 读取出的时间等非 JSON 原生对象。"""

        if isinstance(value, datetime | date):
            return value.isoformat()
        return str(value)

    def _parse_research_brief_result(
        self,
        raw_result: Any,
        project: dict[str, Any] | None,
    ) -> ResearchBriefResult:
        """解析研究任务书和大纲生成结果。

        输入为 DeepAgents 原始输出和项目文档；输出为 ResearchBriefResult。该函数负责
        兼容 dict、Pydantic 对象和占位输出。
        """

        if isinstance(raw_result, ResearchBriefResult):
            return raw_result
        raw_data = self._as_dict(raw_result)
        if "research_brief" in raw_data and "outline" in raw_data:
            return ResearchBriefResult.model_validate(raw_data)
        return self._build_placeholder_research_brief_result(project=project)

    def _parse_outline_result(
        self,
        raw_result: Any,
        fallback_outline: list[OutlineNode],
    ) -> list[OutlineNode]:
        """解析大纲修订结果。

        输入为 DeepAgents 原始输出和回退大纲；输出为 OutlineNode 列表。解析失败时返回
        原大纲，避免后台任务因为格式问题保存空大纲。
        """

        if isinstance(raw_result, list):
            return [OutlineNode.model_validate(node) for node in raw_result]
        raw_data = self._as_dict(raw_result)
        outline = raw_data.get("outline")
        if isinstance(outline, list):
            return [OutlineNode.model_validate(node) for node in outline]
        return fallback_outline

    def _parse_research_result(
        self,
        raw_result: Any,
        project: dict[str, Any] | None,
        outline: list[OutlineNode],
    ) -> ResearchResult:
        """解析研究执行结果。

        输入为 manager_agent 原始输出、项目文档和回退大纲；输出为 ResearchResult。
        支持 `{research_result: {...}}` 和直接 ResearchResult 两种结构。
        """

        if isinstance(raw_result, ResearchResult):
            return raw_result
        raw_data = self._as_dict(raw_result)
        research_result = raw_data.get("research_result")
        if isinstance(research_result, dict):
            return ResearchResult.model_validate(research_result)
        if "title" in raw_data and "sections" in raw_data:
            return ResearchResult.model_validate(raw_data)
        return self._build_placeholder_research_result(project=project, outline=outline)

    def _parse_report_generation_result(
        self,
        raw_result: Any,
        project: dict[str, Any] | None,
    ) -> ReportGenerationResult:
        """解析报告生成结果。

        输入为 DeepAgents 原始输出和项目文档；输出为 ReportGenerationResult。该函数
        保证 background 总能拿到稳定字段。
        """

        if isinstance(raw_result, ReportGenerationResult):
            return raw_result
        raw_data = self._as_dict(raw_result)
        if "title" in raw_data and "html" in raw_data:
            normalized_result = self._fill_report_generation_cards(
                raw_data=raw_data,
                project=project,
            )
            return ReportGenerationResult.model_validate(normalized_result)
        return self._build_placeholder_report_generation_result(project=project)

    def _fill_report_generation_cards(
        self,
        raw_data: dict[str, Any],
        project: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """为报告渲染结果补齐研究过程卡片。

        输入为确定性渲染工具返回的 title/html/sources 和项目文档；输出为可校验的
        ReportGenerationResult 字典。渲染阶段只负责展示转换，因此 fact_cards 和
        insight_cards 优先来自落库 research_result。
        """

        result = dict(raw_data)
        project_data = project or {}
        research_result = project_data.get("research_result")
        if isinstance(research_result, dict):
            result.setdefault("fact_cards", research_result.get("fact_cards", []))
            result.setdefault("insight_cards", research_result.get("insight_cards", []))
        result.setdefault("fact_cards", project_data.get("fact_cards", []))
        result.setdefault("insight_cards", project_data.get("insight_cards", []))
        return result

    def _is_placeholder_report_result(self, result: ReportGenerationResult) -> bool:
        """判断报告渲染结果是否仍为 MVP 占位内容。"""

        html = result.html
        source_types = {source.source_type for source in result.sources}
        placeholder_markers = [
            "Agent 门面占位输出",
            "MVP 占位来源",
            "正式内容将在 DeepAgents 接入后生成",
        ]
        return any(marker in html for marker in placeholder_markers) or "placeholder" in source_types

    def _build_placeholder_result(self, task_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """生成占位任务结果。

        输入为任务名称和任务载荷；输出为与目标结果结构兼容的字典。该函数只服务 MVP
        联调，真实 DeepAgents 接入后不会作为主路径。
        """

        project = payload.get("project") if isinstance(payload.get("project"), dict) else {}
        if task_name == "generate_research_brief":
            return self._build_placeholder_research_brief_result(project=project).model_dump(
                mode="python"
            )
        if task_name == "revise_outline":
            outline = payload.get("outline")
            return {"outline": outline if isinstance(outline, list) else []}
        if task_name == "generate_report":
            project_data = project if isinstance(project, dict) else {}
            outline_data = (
                payload.get("outline")
                if isinstance(payload.get("outline"), list)
                else []
            )
            outline = [OutlineNode.model_validate(node) for node in outline_data]
            return {
                "research_result": self._build_placeholder_research_result(
                    project=project_data,
                    outline=outline,
                ).model_dump(mode="python")
            }
        return {}

    def _build_placeholder_research_brief_result(
        self,
        project: dict[str, Any] | None,
    ) -> ResearchBriefResult:
        """生成占位研究任务书和大纲。

        输入为项目文档；输出为可保存的 ResearchBriefResult。该函数用于真实 Agent
        接入前的主链路验证。
        """

        project_data = project or {}
        request = (
            project_data.get("request")
            if isinstance(project_data.get("request"), dict)
            else {}
        )
        topic = str(project_data.get("topic") or request.get("topic") or "未命名研究主题")
        research_goal = str(request.get("research_goal") or "形成可执行的研究判断")
        target_audience = str(request.get("target_audience") or "业务决策团队")
        research_brief = ResearchBrief(
            topic=topic,
            research_goal=research_goal,
            target_audience=target_audience,
            scope_summary="基于用户输入的地域、时间和业务目标界定研究范围。",
            key_questions=[
                "研究对象的定义和边界是什么",
                "未来关键变化和机会来自哪里",
                "需要重点关注哪些风险和不确定性",
            ],
            assumptions=["当前为占位任务书，真实内容将在 DeepAgents 接入后生成。"],
            success_criteria=["报告包含明确结论", "关键事实具备来源追溯"],
        )
        outline = [
            OutlineNode(
                node_id="1",
                title="研究边界和核心问题",
                question=f"{topic} 的定义、范围和关键判断问题是什么",
                description="明确研究对象、研究边界、目标读者和最终需要回答的问题。",
                children=[],
            ),
            OutlineNode(
                node_id="2",
                title="现状、驱动因素和不确定性",
                question="当前现状如何，未来变化主要由哪些因素驱动",
                description="梳理市场、技术、政策、供需和竞争等关键变量。",
                children=[],
            ),
            OutlineNode(
                node_id="3",
                title="机会判断和行动建议",
                question="未来机会、风险和建议行动是什么",
                description="形成面向目标读者的判断结论和后续行动建议。",
                children=[],
            ),
        ]
        return ResearchBriefResult(research_brief=research_brief, outline=outline)

    def _build_placeholder_research_result(
        self,
        project: dict[str, Any] | None,
        outline: list[OutlineNode],
    ) -> ResearchResult:
        """生成占位研究结果。

        输入为项目文档和已确认大纲；输出为可落库的 ResearchResult。该结果明确标记为
        占位研究内容，避免渲染阶段自行补写研究结论。
        """

        project_data = project or {}
        topic = str(project_data.get("topic") or "未命名研究主题")
        source = ReportSource(
            title="MVP 占位来源",
            url=None,
            published_at=None,
            source_type="placeholder",
        )
        fact_card = FactCard(
            fact_id="fact-1",
            statement="当前研究结果为占位内容，尚未接入真实检索来源。",
            source_ids=["source-1"],
            confidence="low",
        )
        insight_card = InsightCard(
            insight_id="insight-1",
            title="待接入真实研究执行链路",
            summary="主研究智能体接入真实检索后，将生成完整章节正文和证据链。",
            supporting_fact_ids=["fact-1"],
        )
        sections = [
            ResearchSection(
                section_id=node.node_id,
                title=node.title,
                summary=node.question,
                body=(
                    f"{node.description} 当前为占位研究正文，真实内容将在主研究智能体"
                    "完成检索、事实整理和洞察归纳后生成。"
                ),
                key_findings=["当前为占位研究结果"],
                evidence_chain=[
                    EvidenceItem(
                        claim="当前研究结果尚未接入真实检索来源。",
                        fact_ids=["fact-1"],
                        source_ids=["source-1"],
                        confidence="low",
                    )
                ],
                tables=[],
                charts=[],
                risks=["真实研究链路未完成前，不能基于该占位结果做业务决策。"],
            )
            for node in outline
        ]
        if not sections:
            sections = [
                ResearchSection(
                    section_id="summary",
                    title="研究内容",
                    summary=None,
                    body="当前研究过程尚未生成章节正文。",
                    key_findings=[],
                    evidence_chain=[],
                    tables=[],
                    charts=[],
                    risks=["缺少已确认大纲和真实研究结果。"],
                )
            ]
        return ResearchResult(
            title=f"{topic}研究报告",
            executive_summary="当前为占位研究结果，真实摘要将在研究执行链路接入后生成。",
            sections=sections,
            sources=[source],
            fact_cards=[fact_card],
            insight_cards=[insight_card],
        )

    def _build_placeholder_report_generation_result(
        self,
        project: dict[str, Any] | None,
    ) -> ReportGenerationResult:
        """生成占位报告结果。

        输入为项目文档；输出为可保存的 ReportGenerationResult。该函数用于真实检索和
        报告生成 Agent 接入前的接口联调。
        """

        project_data = project or {}
        topic = str(project_data.get("topic") or "未命名研究主题")
        source = ReportSource(
            title="MVP 占位来源",
            url=None,
            published_at=None,
            source_type="placeholder",
        )
        fact_card = FactCard(
            fact_id="fact-1",
            statement="当前报告为占位生成结果，尚未接入真实检索来源。",
            source_ids=["source-1"],
            confidence="low",
        )
        insight_card = InsightCard(
            insight_id="insight-1",
            title="待接入真实研究智能体",
            summary="DeepAgents 接入后将由研究管理智能体协调检索和报告生成。",
            supporting_fact_ids=["fact-1"],
        )
        html = (
            "<html><body>"
            f"<h1>{topic}研究报告</h1>"
            "<p>当前为 Agent 门面占位输出，正式内容将在 DeepAgents 接入后生成。</p>"
            "<h2>参考来源</h2><ol><li>MVP 占位来源</li></ol>"
            "</body></html>"
        )
        return ReportGenerationResult(
            title=f"{topic}研究报告",
            html=html,
            sources=[source],
            fact_cards=[fact_card],
            insight_cards=[insight_card],
        )

    def _as_dict(self, value: Any) -> dict[str, Any]:
        """把框架输出转换为字典。

        输入为任意 DeepAgents 输出对象；输出为字典。该函数只做格式兼容，不做业务
        字段补全。
        """

        if isinstance(value, dict):
            extracted = self._extract_json_from_messages(value)
            return extracted or value
        if isinstance(value, BaseModel):
            return value.model_dump(mode="python")
        return {}

    def _extract_json_from_messages(self, value: dict[str, Any]) -> dict[str, Any]:
        """从 LangChain/DeepAgents messages 中提取最终 JSON。"""

        messages = value.get("messages")
        if not isinstance(messages, list):
            return {}
        for message in reversed(messages):
            content = self._extract_message_content(message)
            parsed = self._parse_json_text(content)
            if parsed:
                return parsed
        return {}

    def _extract_message_content(self, message: Any) -> str:
        """兼容 dict 消息和 LangChain message 对象，提取文本内容。"""

        if isinstance(message, dict):
            content = message.get("content")
        else:
            content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "\n".join(parts)
        return ""

    def _parse_json_text(self, text: str) -> dict[str, Any]:
        """解析模型消息中的 JSON object。"""

        stripped = text.strip()
        if not stripped:
            return {}
        if stripped.startswith("```"):
            stripped = stripped.removeprefix("```json").removeprefix("```").strip()
            stripped = stripped.removesuffix("```").strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start < 0 or end <= start:
                return {}
            try:
                parsed = json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                return {}
        return parsed if isinstance(parsed, dict) else {}


_research_agent: ResearchAgent | None = None


def build_research_agent() -> ResearchAgent:
    """构建研究智能体门面。

    输入为空，输出为 ResearchAgent。本函数只构建研究管理智能体；报告渲染阶段走
    确定性 write_html_report，不再构建独立 LLM report agent。
    """

    manager_agent = _build_deepagents_manager_agent()
    return ResearchAgent(manager_agent=manager_agent, report_agent=None)


def get_research_agent() -> ResearchAgent:
    """获取当前进程内复用的研究智能体门面。

    输入为空，输出为 ResearchAgent 单例。background 通过该函数获取稳定的业务能力，
    不直接依赖 DeepAgents 框架对象。
    """

    global _research_agent
    if _research_agent is None:
        _research_agent = build_research_agent()
        logger.info("研究智能体门面已初始化")
    return _research_agent


def _build_deepagents_manager_agent() -> Any | None:
    """构建 DeepAgents 研究管理主智能体。

    输入为空，输出为 DeepAgents agent 对象。主智能体负责研究规划和协调检索子
    智能体；报告渲染不再挂在 manager_agent 下，而是由确定性渲染流程执行。
    """

    settings: Settings = get_settings()
    model_name = _build_model_name(settings=settings)
    subagents = [_build_search_subagent(model_name=model_name)]
    return create_deep_agent(
        model=model_name,
        tools=[save_research_section],
        system_prompt=_load_prompt(RESEARCH_MANAGER_PROMPT_PATH),
        subagents=subagents,
        name="research-manager-agent",
        checkpointer=MemorySaver(),
    )


def _build_search_subagent(model_name: str) -> dict[str, Any]:
    """构建信息检索子智能体配置。

    输入为模型名称，输出为 DeepAgents subagent 配置字典。该子智能体只持有检索和网页
    阅读相关工具，不直接生成最终报告。
    """
    settings:Settings = get_settings()
    if settings.enable_ragflow:
        tools = [external_search,read_web_page,ragflow_search]
    else:
        tools = [external_search,read_web_page]
    return {
        "name": "search-agent",
        "description": "负责公开互联网检索、网页读取、RAGFlow 内部知识库检索和证据整理。",
        "system_prompt": _load_prompt(SEARCH_AGENT_PROMPT_PATH),
        "tools": tools,
        "model": model_name,
    }

def _build_model_name(settings: Settings) -> str:
    """构建 DeepAgents 可识别的模型名称。

    输入为系统配置，输出为 LangChain/DeepAgents 模型标识。第一版通过配置选择
    openai 或 deepseek，具体 API Key 和 base_url 由运行环境配置。
    """

    provider = settings.llm_provider.lower()
    if provider == "deepseek":
        return f"deepseek:{settings.llm_model_name}"
    if provider == "openai":
        return f"openai:{settings.llm_model_name}"
    return f"{provider}:{settings.llm_model_name}"


def _load_prompt(prompt_path: Path) -> str:
    """读取智能体系统 Prompt。

    输入为 Prompt 文件路径，输出为文件文本内容。Prompt 必须维护在外部 Markdown
    文件中，避免散落硬编码在业务代码里。
    """

    return prompt_path.read_text(encoding="utf-8").strip()
