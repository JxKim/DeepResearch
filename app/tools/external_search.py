from typing import Any

import httpx
from loguru import logger

from app.config.config import get_settings

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
REQUEST_TIMEOUT_SECONDS = 30


async def external_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    time_range: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """执行公开互联网搜索。

    输入为搜索问题和可选过滤条件；输出为归一化搜索结果。当前实现优先调用 Tavily
    Search API；未配置 API Key 时返回可解释的跳过结果，避免智能体编造来源。
    """

    normalized_query = query.strip()
    if not normalized_query:
        return {
            "status": "error",
            "provider": "tavily",
            "query": query,
            "results": [],
            "error": "query 不能为空",
        }

    settings = get_settings()
    if not settings.tavily_api_key:
        logger.warning("Tavily API Key 未配置，跳过公开互联网搜索")
        return {
            "status": "skipped",
            "provider": "tavily",
            "query": normalized_query,
            "results": [],
            "error": "TAVILY_API_KEY 未配置",
        }

    payload: dict[str, Any] = {
        "query": normalized_query,
        "max_results": max(1, min(max_results, 10)),
        "search_depth": search_depth if search_depth in {"basic", "advanced"} else "basic",
        "include_answer": False,
        "include_raw_content": False,
    }
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains
    if time_range:
        payload["time_range"] = time_range
    if start_date:
        payload["start_date"] = start_date
    if end_date:
        payload["end_date"] = end_date

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                TAVILY_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {settings.tavily_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            response_data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Tavily 搜索失败，query={}, error={}", normalized_query, exc)
        return {
            "status": "error",
            "provider": "tavily",
            "query": normalized_query,
            "results": [],
            "error": str(exc),
        }

    results = [_normalize_tavily_result(item) for item in response_data.get("results", [])]
    logger.info("公开互联网搜索完成，query={}, results={}", normalized_query, len(results))
    return {
        "status": "ok",
        "provider": "tavily",
        "query": normalized_query,
        "answer": response_data.get("answer"),
        "results": results,
    }


def _normalize_tavily_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title"),
        "url": item.get("url"),
        "published_at": item.get("published_date"),
        "score": item.get("score"),
        "content": item.get("content"),
        "source_type": "public_web",
    }
