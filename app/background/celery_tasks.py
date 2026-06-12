import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.background import research_tasks
from app.celery_app import celery_app

_work_loop: asyncio.AbstractEventLoop | None = None

def _get_worker_loop() -> asyncio.AbstractEventLoop:
    global _work_loop
    if _work_loop is None:
        _work_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_work_loop)
    
    return _work_loop

def _run_async(coroutine_factory: Callable[[], Awaitable[None]]) -> None:
    """在 Celery 的同步 worker 入口中执行异步业务函数。"""
    loop = _get_worker_loop()
    loop.run_until_complete(coroutine_factory())


def _task_options(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "autoretry_for": (Exception,),
        "retry_kwargs": {"max_retries": 3},
        "retry_backoff": True,
        "retry_jitter": True,
    }


@celery_app.task(**_task_options("research.generate_research_brief"))
def generate_research_brief_task(project_id: str, task_id: str) -> None:
    
    _run_async(
        lambda: research_tasks.run_generate_research_brief_task(
            project_id=project_id,
            task_id=task_id,
        )
    )


@celery_app.task(**_task_options("research.revise_outline"))
def revise_outline_task(project_id: str, task_id: str, revision_instruction: str) -> None:
    _run_async(
        lambda: research_tasks.run_revise_outline_task(
            project_id=project_id,
            task_id=task_id,
            revision_instruction=revision_instruction,
        )
    )


@celery_app.task(**_task_options("research.generate_report"))
def generate_report_task(
    project_id: str,
    task_id: str,
    user_instruction: str | None,
) -> None:
    _run_async(
        lambda: research_tasks.run_generate_report_task(
            project_id=project_id,
            task_id=task_id,
            user_instruction=user_instruction,
        )
    )


@celery_app.task(**_task_options("research.render_report"))
def render_report_task(
    project_id: str,
    task_id: str,
    user_instruction: str | None,
) -> None:
    _run_async(
        lambda: research_tasks.run_render_report_task(
            project_id=project_id,
            task_id=task_id,
            user_instruction=user_instruction,
        )
    )
