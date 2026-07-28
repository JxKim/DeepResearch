import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.utils import create_file_data
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger
from pydantic import BaseModel

from app.config.config import Settings, get_settings
from app.repository import research_project_repository
from app.schemas import (
    OutlineNode,
    ReportGenerationResult,
    ReportSource,
    ResearchBriefResult,
    ResearchResult,
    ResearchSection,
    ResearchSynthesis,
)
from app.tools.external_search import external_search
from app.tools.ragflow_search import ragflow_search
from app.tools.report_writer import write_html_report
from app.tools.research_workspace import save_research_section
from app.tools.web_reader import read_web_page

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
RESEARCH_MANAGER_PROMPT_PATH = PROMPT_DIR / "research_manager.md"
SEARCH_AGENT_PROMPT_PATH = PROMPT_DIR / "search_agent.md"


class ResearchAgent:
    """研究智能体业务门面。

    输入为 DeepAgents 研究管理智能体；输出为 background 可直接调用的四个业务方法。
    该类隔离研究准备、研究过程和确定性报告渲染的框架细节。
    """

    def __init__(self, manager_agent: Any) -> None:
        """初始化研究智能体门面。

        输入为 DeepAgents 研究管理智能体；输出为空。manager_agent 负责研究准备、
        大纲和逐章节研究，报告渲染由确定性工具完成。
        """

        self.manager_agent = manager_agent

    async def generate_research_brief(self, project: dict[str, Any] | None) -> ResearchBriefResult:
        """生成研究任务书和大纲草案。

        输入为研究项目文档；输出为研究任务书和大纲节点列表。该方法负责把项目数据
        转换为 DeepAgents 输入，并解析结构化输出。
        """

        payload = {
            "task_name": "generate_research_brief",
            "project": project or {},
            "expected_output": "ResearchBriefResult",
        }
        raw_result = await self._invoke_manager_agent(
            task_name="generate_research_brief",
            payload=payload,
        )
        result = self._parse_research_brief_result(raw_result=raw_result)
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

        payload = {
            "task_name": "revise_outline",
            "project": project or {},
            "outline": [node.model_dump(mode="python") for node in outline],
            "revision_instruction": revision_instruction,
            "expected_output": "list[OutlineNode]",
        }
        raw_result = await self._invoke_manager_agent(
            task_name="revise_outline",
            payload=payload,
        )
        revised_outline = self._parse_outline_result(raw_result=raw_result)
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
        expected_section_ids = self._limited_research_section_ids(outline=outline)
        sections = await research_project_repository.get_research_sections(project_id=project_id)
        saved_section_ids = {
            str(section.get("section_id"))
            for section in sections
            if isinstance(section, dict) and section.get("section_id")
        }
        if saved_section_ids:
            logger.info(
                "检测到已保存研究章节，将继续补写缺失章节，project_id={}，saved={}",
                project_id,
                sorted(saved_section_ids),
            )
        else:
            await research_project_repository.clear_research_sections(project_id=project_id)

        missing_section_ids = sorted(expected_section_ids - saved_section_ids)
        for attempt in range(1, 5):
            if not missing_section_ids:
                break
            payload = {
                "task_name": "generate_report",
                "project": project or {},
                "outline": [node.model_dump(mode="python") for node in outline],
                "user_instruction": user_instruction,
                "expected_output": "save sections with save_research_section",
                "required_section_ids": sorted(expected_section_ids),
                "missing_section_ids": missing_section_ids,
                "attempt": attempt,
            }
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
        project_after_research = await research_project_repository.get_project(
            project_id=project_id
        )
        result = self._build_research_result_from_saved_sections(
            sections=sections,
            sources=await research_project_repository.get_research_sources(project_id=project_id),
            project=project_after_research or project,
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
        user_instruction: str | None,
    ) -> ReportGenerationResult:
        """渲染 HTML 研究报告。

        输入为已完成研究章节的项目和可选展示要求；输出为报告标题、HTML、来源和事实
        卡片。ResearchResult 在渲染前临时组装，不作为项目字段落库。
        """

        project_data = project or {}
        research_result = self._build_research_result_from_project(project=project_data)
        payload = {
            "task_name": "render_report",
            "project_id": project_data.get("project_id"),
            "research_result": research_result.model_dump(mode="python"),
            "user_instruction": user_instruction,
            "expected_output": "ReportGenerationResult",
        }
        raw_result = await write_html_report(
            research_result=payload["research_result"],
            layout_plan=self._build_default_layout_plan(payload=payload),
        )
        result = self._parse_report_generation_result(raw_result=raw_result, project=project)
        logger.info("研究报告结果已生成，title={}", result.title)
        return result

    def _build_default_layout_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        """构建确定性报告渲染版式计划。"""

        user_instruction = payload.get("user_instruction")
        return {
            "subtitle": user_instruction if isinstance(user_instruction, str) else None,
            "theme": "professional",
        }

    def _build_research_result_from_project(
        self,
        project: dict[str, Any],
    ) -> ResearchResult:
        """从项目当前 sections/sources 临时组装渲染输入。

        输入为 repository 返回的项目文档；输出为确定性渲染工具可渲染的 ResearchResult。
        缺少章节时明确失败，不在渲染阶段补写内容。
        """

        sections = project.get("sections")
        if not isinstance(sections, list) or not sections:
            raise ValueError("项目缺少已保存的研究章节，无法渲染报告")
        return self._build_research_result_from_saved_sections(
            sections=sections,
            sources=project.get("sources") if isinstance(project.get("sources"), list) else [],
            project=project,
            outline=[],
        )

    def _build_research_result_from_saved_sections(
        self,
        sections: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        project: dict[str, Any] | None,
        outline: list[OutlineNode],
    ) -> ResearchResult:
        """从主研究智能体已落库章节组装 ResearchResult。"""

        project_data = project or {}
        expected_section_ids = self._limited_research_section_ids(outline=outline)
        saved_sections = [
            ResearchSection.model_validate(section)
            for section in sections
            if isinstance(section, dict)
        ]
        saved_section_ids = {section.section_id for section in saved_sections}
        missing_section_ids = sorted(expected_section_ids - saved_section_ids)
        if not saved_sections:
            raise ValueError("主研究智能体没有通过 save_research_section 保存任何章节")
        if expected_section_ids and missing_section_ids:
            raise ValueError(f"主研究智能体缺少章节研究结果: {', '.join(missing_section_ids)}")

        self._validate_saved_research_sections(saved_sections)
        topic = str(project_data.get("topic") or "未命名研究主题")
        saved_sources = self._collect_saved_sources(
            sources=sources,
            sections=sections,
        )
        synthesis = self._build_synthesis_from_sections(saved_sections)
        return ResearchResult(
            title=f"{topic}研究报告",
            executive_summary=synthesis.executive_summary,
            sections=saved_sections,
            sources=saved_sources,
            fact_cards=[],
            synthesis=synthesis,
        )

    def _collect_saved_sources(
        self,
        sources: list[dict[str, Any]],
        sections: list[dict[str, Any]],
    ) -> list[ReportSource]:
        """按 source_id 保留报告正文实际引用的来源详情。

        项目级 sources 可以按 URL 去重，但章节引用使用各自保存时的 source_id。
        渲染输入必须保留这些 ID 别名，否则同 URL 来源会覆盖彼此并产生悬空引用。
        """

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

    def _extract_sources_from_sections(
        self,
        sections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        section_sources: list[dict[str, Any]] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            for source in section.get("sources") or []:
                if isinstance(source, dict):
                    section_sources.append(source)
        return section_sources

    def _expected_research_section_ids(self, outline: list[OutlineNode]) -> list[str]:
        """计算需要落库正文的章节节点。优先使用叶子节点；没有叶子时使用顶层节点。"""

        leaf_ids: list[str] = []
        all_ids: list[str] = []
        for node in outline:
            self._collect_outline_node_ids(node=node, all_ids=all_ids, leaf_ids=leaf_ids)
        return leaf_ids or all_ids

    def _limited_research_section_ids(self, outline: list[OutlineNode]) -> set[str]:
        """按配置限制本轮需要完整研究并落库的章节数量。"""

        section_ids = self._expected_research_section_ids(outline=outline)
        settings = get_settings()
        if settings.report_max_sections is None or len(section_ids) <= settings.report_max_sections:
            return set(section_ids)
        limited_ids = section_ids[: settings.report_max_sections]
        logger.info(
            "已限制本轮研究章节数量，configured_max={}，original={}，selected={}",
            settings.report_max_sections,
            len(section_ids),
            limited_ids,
        )
        return set(limited_ids)

    def _collect_outline_node_ids(
        self,
        node: OutlineNode,
        all_ids: list[str],
        leaf_ids: list[str],
    ) -> None:
        all_ids.append(node.node_id)
        if not node.children:
            leaf_ids.append(node.node_id)
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
                    " ".join(self._section_finding_claims(section)),
                    " ".join(self._section_risk_descriptions(section)),
                ]
            )
            if any(marker in section_text for marker in placeholder_markers):
                raise ValueError(f"章节 {section.section_id} 包含占位内容")
            if not section.body.strip():
                raise ValueError(f"章节 {section.section_id} 缺少正文")
            if not section.key_findings:
                raise ValueError(f"章节 {section.section_id} 缺少关键发现")
            section_source_ids = {
                source.source_id for source in section.sources if source.source_id
            }
            referenced_source_ids = self._section_referenced_source_ids(section)
            missing_source_ids = referenced_source_ids - section_source_ids
            if missing_source_ids:
                raise ValueError(
                    f"章节 {section.section_id} 缺少来源详情: "
                    f"{', '.join(sorted(missing_source_ids))}"
                )
            for source in section.sources:
                if not source.source_id:
                    raise ValueError(f"章节 {section.section_id} 存在缺少 source_id 的来源")
                if (
                    source.source_type != "internal_knowledge_base"
                    and not self._is_http_url(source.url)
                ):
                    raise ValueError(
                        f"章节 {section.section_id} 的公开来源 {source.source_id} 缺少 http(s) URL"
                    )

    @staticmethod
    def _is_http_url(value: str | None) -> bool:
        return bool(value and value.startswith(("http://", "https://")))

    def _build_synthesis_from_sections(self, sections: list[ResearchSection]) -> ResearchSynthesis:
        """从已完成章节确定性生成全局研究综合。"""

        core_conclusions: list[str] = []
        cross_section_insights: list[str] = []
        strategic_recommendations: list[str] = []
        global_risks: list[str] = []
        for section in sections:
            finding_claims = self._section_finding_claims(section)
            risk_descriptions = self._section_risk_descriptions(section)
            if section.summary:
                core_conclusions.append(section.summary)
            core_conclusions.extend(finding_claims[:2])
            if section.summary or finding_claims:
                cross_section_insights.append(
                    f"{section.title}: {section.summary or finding_claims[0]}"
                )
            global_risks.extend(risk_descriptions[:2])

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

    @staticmethod
    def _section_finding_claims(section: ResearchSection) -> list[str]:
        return [finding.claim for finding in section.key_findings if finding.claim.strip()]

    @staticmethod
    def _section_risk_descriptions(section: ResearchSection) -> list[str]:
        return [risk.description for risk in section.risks if risk.description.strip()]

    @staticmethod
    def _section_referenced_source_ids(section: ResearchSection) -> set[str]:
        source_ids: set[str] = set()
        for finding in section.key_findings:
            source_ids.update(source_id for source_id in finding.source_ids if source_id)
        for risk in section.risks:
            source_ids.update(source_id for source_id in risk.source_ids if source_id)
        return source_ids

    async def _invoke_manager_agent(self, task_name: str, payload: dict[str, Any]) -> Any:
        """调用研究管理智能体。

        输入为任务名称和任务载荷；输出为 DeepAgents 原始结果。调用时注入 thread_id
        和虚拟文件系统初始文件。
        """

        task_json = json.dumps(payload, ensure_ascii=False, indent=2, default=self._json_default)
        return await self.manager_agent.ainvoke(
            {
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
                        "该目录用于保存检索摘要、来源整理、事实卡片、章节发现、风险说明和报告草稿。"
                    ),
                },
            },
            config=self._build_deepagents_config(payload=payload),
        )

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
    ) -> ResearchBriefResult:
        """解析研究任务书和大纲生成结果。

        输入为 DeepAgents 原始输出；输出为 ResearchBriefResult。无法解析时明确失败。
        """

        if isinstance(raw_result, ResearchBriefResult):
            return raw_result
        raw_data = self._as_dict(raw_result)
        if "research_brief" in raw_data and "outline" in raw_data:
            return ResearchBriefResult.model_validate(raw_data)
        raise ValueError("研究管理智能体未返回有效的 research_brief 和 outline")

    def _parse_outline_result(
        self,
        raw_result: Any,
    ) -> list[OutlineNode]:
        """解析大纲修订结果。

        输入为 DeepAgents 原始输出；输出为 OutlineNode 列表。无法解析时明确失败。
        """

        if isinstance(raw_result, list):
            return [OutlineNode.model_validate(node) for node in raw_result]
        raw_data = self._as_dict(raw_result)
        outline = raw_data.get("outline")
        if isinstance(outline, list):
            return [OutlineNode.model_validate(node) for node in outline]
        raise ValueError("研究管理智能体未返回有效的 outline")

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
        raise ValueError("报告渲染器未返回有效的 title 和 html")

    def _fill_report_generation_cards(
        self,
        raw_data: dict[str, Any],
        project: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """为报告渲染结果补齐研究过程卡片。

        输入为确定性渲染工具返回的 title/html/sources 和项目文档；输出为可校验的
        ReportGenerationResult 字典。渲染阶段只负责展示转换，不生成 fact_cards。
        """

        result = dict(raw_data)
        result.setdefault("fact_cards", [])
        return result

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
    return ResearchAgent(manager_agent=manager_agent)


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


def _build_deepagents_manager_agent() -> Any:
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
    settings: Settings = get_settings()
    if settings.enable_ragflow:
        tools = [external_search, read_web_page, ragflow_search]
    else:
        tools = [external_search, read_web_page]
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
