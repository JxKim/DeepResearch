import asyncio

import pytest

from app.agents.research_agent import ResearchAgent
from app.repository import research_project_repository
from app.schemas import ProjectStatus, ResearchBriefResult, ResearchProject
from app.tools import research_workspace
from app.tools.report_writer import write_html_report


def test_save_research_section_accepts_structured_findings(monkeypatch):
    saved_sections = []
    merged_sources = []

    async def fake_get_project(project_id):
        return {
            "project_id": project_id,
            "confirmed_outline": [{"node_id": "1", "children": []}],
        }

    async def fake_upsert_section(project_id, section):
        saved_sections.append(section)

    async def fake_upsert_sources(project_id, sources):
        merged_sources.extend(sources)

    monkeypatch.setattr(
        research_workspace.research_project_repository,
        "get_project",
        fake_get_project,
    )
    monkeypatch.setattr(
        research_workspace.research_project_repository,
        "upsert_research_section",
        fake_upsert_section,
    )
    monkeypatch.setattr(
        research_workspace.research_project_repository,
        "upsert_research_sources",
        fake_upsert_sources,
    )

    section = {
        "section_id": "1",
        "title": "政策驱动",
        "summary": "政策驱动明确，但商业化仍需验证。",
        "body": (
            "政策驱动正在成为本阶段研究对象的重要外部变量。公开来源显示，相关政策已经把"
            "基础设施、运行服务和应用场景纳入重点方向，这说明产业具备继续跟踪的必要性。"
            "与此同时，现有资料仍不足以证明商业化已经进入规模化兑现阶段，因此章节结论"
            "需要保留证据限制，并持续跟踪后续公开数据。"
        ),
        "key_findings": [
            {
                "finding_id": "finding-1",
                "claim": "政策和基础设施是主要外部驱动。",
                "source_ids": ["source-1"],
                "confidence": "high",
            }
        ],
        "risks": [
            {
                "risk_id": "risk-1",
                "description": "商业化节奏仍缺少收入数据验证。",
                "source_ids": ["source-1"],
                "risk_type": "evidence_gap",
                "severity": "medium",
            }
        ],
        "sources": [
            {
                "source_id": "source-1",
                "title": "Source One",
                "url": "https://example.com/source",
                "source_type": "public_web",
            }
        ],
    }

    result = asyncio.run(research_workspace.save_research_section("project-1", section))

    assert result["ok"] is True
    assert saved_sections[0]["key_findings"][0]["claim"] == "政策和基础设施是主要外部驱动。"
    assert saved_sections[0]["risks"][0]["risk_type"] == "evidence_gap"
    assert "evidence_chain" not in saved_sections[0]
    assert saved_sections[0]["sources"][0]["source_id"] == "source-1"
    assert merged_sources[0]["source_id"] == "source-1"
    assert result["sources_merged"] == 1


def test_research_project_keeps_sources_top_level_without_research_result_storage():
    project = ResearchProject.model_validate(
        {
            "project_id": "project-1",
            "topic": "测试主题",
            "request": {"topic": "测试主题"},
            "status": ProjectStatus.CREATED,
            "sections": [],
            "sources": [
                {
                    "source_id": "source-1",
                    "title": "Source One",
                    "url": "https://example.com/source",
                    "source_type": "public_web",
                }
            ],
            "created_at": "2026-07-28T00:00:00+00:00",
            "updated_at": "2026-07-28T00:00:00+00:00",
        }
    )

    dumped_project = project.model_dump(mode="python")

    assert dumped_project["sources"][0]["source_id"] == "source-1"
    assert "fact_cards" not in dumped_project
    assert "research_result" not in dumped_project


def test_project_source_merge_uses_url_not_section_local_source_id(monkeypatch):
    operations = []

    class FakeCollection:
        async def update_one(self, query, update):
            operations.append((query, update))

    monkeypatch.setattr(
        research_project_repository,
        "_get_collection",
        lambda: FakeCollection(),
    )

    asyncio.run(
        research_project_repository.upsert_research_sources(
            project_id="project-1",
            sources=[
                {
                    "source_id": "source-1",
                    "title": "Source A",
                    "url": "https://example.com/a",
                    "source_type": "public_web",
                },
                {
                    "source_id": "source-1",
                    "title": "Source B",
                    "url": "https://example.com/b",
                    "source_type": "public_web",
                },
            ],
        )
    )

    pull_updates = [
        update["$pull"]["sources"]
        for _, update in operations
        if "$pull" in update and "sources" in update["$pull"]
    ]

    assert pull_updates == [
        {"url": "https://example.com/a"},
        {"url": "https://example.com/b"},
    ]


def test_report_writer_renders_structured_findings_and_risks():
    research_result = {
        "title": "测试研究报告",
        "executive_summary": "核心摘要",
        "sources": [
            {
                "source_id": "source-1",
                "title": "Source One",
                "url": "https://example.com/source",
                "source_type": "public_web",
            }
        ],
        "sections": [
            {
                "section_id": "1",
                "title": "政策驱动",
                "body": "本章正文。",
                "key_findings": [
                    {
                        "finding_id": "finding-1",
                        "claim": "政策和基础设施是主要外部驱动。",
                        "source_ids": ["source-1", "source-missing"],
                        "confidence": "high",
                    }
                ],
                "risks": [
                    {
                        "risk_id": "risk-1",
                        "description": "商业化节奏仍缺少收入数据验证。",
                        "source_ids": ["source-1"],
                        "risk_type": "evidence_gap",
                        "severity": "medium",
                    }
                ],
            }
        ],
    }

    result = asyncio.run(write_html_report(research_result=research_result))

    assert "政策和基础设施是主要外部驱动。" in result["html"]
    assert "商业化节奏仍缺少收入数据验证。" in result["html"]
    assert "#ref-source-1" in result["html"]
    assert 'id="ref-source-missing"' in result["html"]
    assert "来源详情缺失（source-missing）" in result["html"]


def test_report_source_collection_preserves_section_source_ids_for_same_url():
    agent = ResearchAgent(manager_agent=None)
    shared_url = "https://example.com/shared-source"

    sources = agent._collect_saved_sources(
        sources=[
            {
                "source_id": "source-project",
                "title": "项目级来源",
                "url": shared_url,
                "source_type": "public_web",
            }
        ],
        sections=[
            {
                "section_id": "1.1",
                "sources": [
                    {
                        "source_id": "source-1.1-1",
                        "title": "章节来源",
                        "url": shared_url,
                        "source_type": "public_web",
                    }
                ],
            }
        ],
    )

    assert {source.source_id for source in sources} == {
        "source-project",
        "source-1.1-1",
    }


def test_research_agent_rejects_invalid_brief_output_without_placeholder():
    class InvalidManagerAgent:
        async def ainvoke(self, *_args, **_kwargs):
            return {"messages": [{"role": "assistant", "content": "{}"}]}

    research_agent = ResearchAgent(manager_agent=InvalidManagerAgent())

    with pytest.raises(ValueError, match="research_brief 和 outline"):
        asyncio.run(
            research_agent.generate_research_brief(
                project={"project_id": "project-1", "topic": "测试主题"}
            )
        )


def test_research_brief_fills_missing_outline_descriptions():
    result = ResearchBriefResult.model_validate(
        {
            "research_brief": {
                "topic": "测试主题",
                "research_goal": "形成研究判断",
                "target_audience": "业务团队",
                "scope_summary": "测试范围",
            },
            "outline": [
                {
                    "node_id": "1",
                    "title": "一级章节",
                    "question": "一级章节回答什么问题",
                    "children": [
                        {
                            "node_id": "1.1",
                            "title": "二级章节",
                            "question": "二级章节回答什么问题",
                            "description": "  ",
                            "children": [],
                        }
                    ],
                }
            ],
        }
    )

    assert result.outline[0].description == "一级章节回答什么问题"
    assert result.outline[0].children[0].description == "二级章节回答什么问题"


def test_research_agent_rejects_report_render_without_saved_sections():
    research_agent = ResearchAgent(manager_agent=object())

    with pytest.raises(ValueError, match="缺少已保存的研究章节"):
        asyncio.run(
            research_agent.generate_report(
                project={"project_id": "project-1", "topic": "测试主题"},
                user_instruction=None,
            )
        )
