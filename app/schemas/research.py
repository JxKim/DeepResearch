from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.schemas import OutlineNode, ProjectStatus, ReportSource


class ResearchBrief(BaseModel):
    """研究任务书结构。"""

    topic: str
    research_goal: str
    target_audience: str
    scope_summary: str
    key_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class FactCard(BaseModel):
    """事实卡片结构。"""

    fact_id: str
    statement: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    evidence_summary: str | None = None


class KeyFinding(BaseModel):
    """章节关键发现。"""

    finding_id: str
    claim: str
    source_ids: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class RiskItem(BaseModel):
    """章节风险、不确定性或冲突说明。"""

    risk_id: str
    description: str
    source_ids: list[str] = Field(default_factory=list)
    risk_type: str = "uncertainty"
    severity: str = "medium"


class ResearchSynthesis(BaseModel):
    """全局研究综合结构。"""

    executive_summary: str | None = None
    core_conclusions: list[str] = Field(default_factory=list)
    cross_section_insights: list[str] = Field(default_factory=list)
    strategic_recommendations: list[str] = Field(default_factory=list)
    global_risks: list[str] = Field(default_factory=list)


class ResearchSection(BaseModel):
    """研究报告章节内容。"""

    section_id: str
    title: str
    summary: str | None = None
    body: str
    key_findings: list[KeyFinding] = Field(default_factory=list)
    sources: list[ReportSource] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    charts: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)

    @field_validator("key_findings", mode="before")
    @classmethod
    def _normalize_key_findings(cls, value: Any) -> list[Any]:
        """兼容旧版字符串关键发现，同时接受新版对象结构。"""

        if value is None:
            return []
        if not isinstance(value, list):
            return value
        normalized: list[Any] = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized.append({"finding_id": f"finding-{index}", "claim": text})
                continue
            if isinstance(item, dict):
                claim = item.get("claim") or item.get("summary") or item.get("title")
                if claim and not item.get("finding_id"):
                    item = {**item, "finding_id": f"finding-{index}"}
                normalized.append(item)
                continue
            normalized.append(item)
        return normalized

    @field_validator("risks", mode="before")
    @classmethod
    def _normalize_risks(cls, value: Any) -> list[Any]:
        """兼容旧版字符串风险，同时接受新版对象结构。"""

        if value is None:
            return []
        if not isinstance(value, list):
            return value
        normalized: list[Any] = []
        for index, item in enumerate(value, start=1):
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized.append({"risk_id": f"risk-{index}", "description": text})
                continue
            if isinstance(item, dict):
                description = item.get("description") or item.get("summary") or item.get("title")
                if description and not item.get("risk_id"):
                    item = {**item, "risk_id": f"risk-{index}"}
                normalized.append(item)
                continue
            normalized.append(item)
        return normalized


class ResearchResult(BaseModel):
    """完整研究结果。"""

    title: str
    executive_summary: str | None = None
    sections: list[ResearchSection] = Field(default_factory=list)
    sources: list[ReportSource] = Field(default_factory=list)
    fact_cards: list[FactCard] = Field(default_factory=list)
    synthesis: ResearchSynthesis | None = None


class ResearchProject(BaseModel):
    """研究项目容器。

    项目顶层保存流程状态、用户输入、大纲、逐章节草稿和全项目去重来源。ResearchResult
    只作为渲染前临时组装的输入对象，不作为项目字段落库。
    """

    project_id: str
    topic: str
    request: dict[str, Any]
    status: ProjectStatus
    outline: list[OutlineNode] = Field(default_factory=list)
    confirmed_outline: list[OutlineNode] = Field(default_factory=list)
    research_brief: ResearchBrief | None = None
    sections: list[ResearchSection] = Field(default_factory=list)
    sources: list[ReportSource] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ResearchBriefResult(BaseModel):
    """研究任务书和大纲生成结果。"""

    research_brief: ResearchBrief
    outline: list[OutlineNode]


class ReportGenerationResult(BaseModel):
    """研究报告生成结果。"""

    title: str
    html: str
    sources: list[ReportSource] = Field(default_factory=list)
    fact_cards: list[FactCard] = Field(default_factory=list)
