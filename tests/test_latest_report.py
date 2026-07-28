import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

import app.routers as research_routers
from app.repository import report_repository
from app.schemas import LatestReportResponse


def test_repository_queries_most_recent_report(monkeypatch):
    query_args = {}

    class FakeCollection:
        async def find_one(self, query, *, sort):
            query_args["query"] = query
            query_args["sort"] = sort
            return None

    monkeypatch.setattr(report_repository, "_get_collection", FakeCollection)

    result = asyncio.run(report_repository.get_most_recent_report())

    assert result is None
    assert query_args == {
        "query": {},
        "sort": [("created_at", -1)],
    }


def test_latest_report_endpoint_returns_project_id(monkeypatch):
    report = LatestReportResponse(
        project_id="project-latest",
        report_id="report-latest",
        version=2,
        title="最新研究报告",
        html="<html><body>report</body></html>",
        sources=[],
        created_at=datetime(2026, 7, 29, tzinfo=UTC),
    )

    async def fake_get_most_recent_report():
        return report

    monkeypatch.setattr(
        research_routers.report_repository,
        "get_most_recent_report",
        fake_get_most_recent_report,
    )

    result = asyncio.run(research_routers.get_most_recent_report())

    assert result.project_id == "project-latest"
    assert result.report_id == "report-latest"


def test_latest_report_endpoint_returns_404_when_empty(monkeypatch):
    async def fake_get_most_recent_report():
        return None

    monkeypatch.setattr(
        research_routers.report_repository,
        "get_most_recent_report",
        fake_get_most_recent_report,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(research_routers.get_most_recent_report())

    assert exc_info.value.status_code == 404
