from typing import Any
from urllib.parse import urljoin

import httpx
from loguru import logger

from app.config.config import get_settings

REQUEST_TIMEOUT_SECONDS = 30


async def ragflow_search(
    query: str,
    dataset_ids: list[str] | None = None,
    document_ids: list[str] | None = None,
    page: int = 1,
    page_size: int = 10,
    similarity_threshold: float = 0.2,
    vector_similarity_weight: float = 0.3,
    top_k: int = 1024,
    keyword: bool = False,
) -> dict[str, Any]:
    """检索 RAGFlow 内部知识库。

    输入为问题、数据集或文档范围；输出为归一化 chunk 列表。dataset_ids 和
    document_ids 至少需要提供一项，否则返回跳过结果。
    """

    normalized_query = query.strip()
    if not normalized_query:
        return {
            "status": "error",
            "provider": "ragflow",
            "query": query,
            "chunks": [],
            "error": "query 不能为空",
        }

    settings = get_settings()
    if not settings.ragflow_base_url or not settings.ragflow_api_key:
        logger.warning("RAGFlow 配置不完整，跳过内部知识库检索")
        return {
            "status": "skipped",
            "provider": "ragflow",
            "query": normalized_query,
            "chunks": [],
            "error": "RAGFLOW_BASE_URL 或 RAGFLOW_API_KEY 未配置",
        }

    if not dataset_ids and not document_ids:
        return {
            "status": "skipped",
            "provider": "ragflow",
            "query": normalized_query,
            "chunks": [],
            "error": "dataset_ids 和 document_ids 至少需要提供一项",
        }

    payload: dict[str, Any] = {
        "question": normalized_query,
        "page": max(1, page),
        "page_size": max(1, min(page_size, 30)),
        "similarity_threshold": max(0.0, min(similarity_threshold, 1.0)),
        "vector_similarity_weight": max(0.0, min(vector_similarity_weight, 1.0)),
        "top_k": max(1, top_k),
        "keyword": keyword,
    }
    if dataset_ids:
        payload["dataset_ids"] = dataset_ids
    if document_ids:
        payload["document_ids"] = document_ids

    retrieval_url = urljoin(str(settings.ragflow_base_url).rstrip("/") + "/", "api/v1/retrieval")
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                retrieval_url,
                headers={
                    "Authorization": f"Bearer {settings.ragflow_api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            response_data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("RAGFlow 检索失败，query={}, error={}", normalized_query, exc)
        return {
            "status": "error",
            "provider": "ragflow",
            "query": normalized_query,
            "chunks": [],
            "error": str(exc),
        }

    if response_data.get("code") not in {0, None}:
        message = response_data.get("message") or "RAGFlow 返回非成功状态"
        return {
            "status": "error",
            "provider": "ragflow",
            "query": normalized_query,
            "chunks": [],
            "error": message,
            "raw": response_data,
        }

    chunks = [_normalize_chunk(item) for item in _extract_chunks(response_data)]
    logger.info("RAGFlow 检索完成，query={}, chunks={}", normalized_query, len(chunks))
    return {
        "status": "ok",
        "provider": "ragflow",
        "query": normalized_query,
        "chunks": chunks,
    }


def _extract_chunks(response_data: dict[str, Any]) -> list[dict[str, Any]]:
    data = response_data.get("data", response_data)
    if isinstance(data, dict):
        chunks = data.get("chunks") or data.get("docs") or data.get("documents") or []
        return chunks if isinstance(chunks, list) else []
    if isinstance(data, list):
        return data
    return []


def _normalize_chunk(item: dict[str, Any]) -> dict[str, Any]:
    content = item.get("content") or item.get("text") or item.get("chunk") or ""
    return {
        "chunk_id": item.get("id") or item.get("chunk_id"),
        "document_id": item.get("document_id") or item.get("doc_id"),
        "dataset_id": item.get("dataset_id"),
        "document_name": item.get("document_name") or item.get("docnm_kwd"),
        "content": content,
        "score": item.get("similarity") or item.get("score"),
        "metadata": item.get("metadata") or {},
        "source_type": "internal_knowledge_base",
    }
