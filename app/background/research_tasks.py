from typing import Any

from loguru import logger

from app.agents.research_agent import get_research_agent
from app.repository import report_repository, research_project_repository, research_task_repository
from app.schemas import ProjectStatus


def start_generate_research_brief_task(project_id: str, task_id: str) -> None:
    """启动研究任务书和大纲生成后台任务。

    输入为研究项目编号和后台任务编号；该函数只负责把任务提交到当前 API 进程的
    asyncio 事件循环，不直接执行 Agent，也不返回任务结果。
    """

    _send_task(
        task_path="research.generate_research_brief",
        task_name="generate_research_brief",
        project_id=project_id,
        task_id=task_id,
        args=(project_id, task_id),
    )


def start_revise_outline_task(
    project_id: str,
    task_id: str,
    revision_instruction: str,
) -> None:
    """启动研究大纲修改后台任务。

    输入为研究项目编号、后台任务编号和用户的自然语言修改要求；该函数只负责启动
    后台执行协程，具体的大纲修改由研究管理智能体完成。
    """

    _send_task(
        task_path="research.revise_outline",
        task_name="revise_outline",
        project_id=project_id,
        task_id=task_id,
        args=(project_id, task_id, revision_instruction),
    )


def start_generate_report_task(
    project_id: str,
    task_id: str,
    user_instruction: str | None,
) -> None:
    """启动研究报告生成后台任务。

    输入为研究项目编号、后台任务编号和可选的研究/报告要求；该函数只负责启动后台
    执行协程，研究结果和报告版本保存由内部执行流程完成。
    """

    _send_task(
        task_path="research.generate_report",
        task_name="generate_report",
        project_id=project_id,
        task_id=task_id,
        args=(project_id, task_id, user_instruction),
    )


def start_render_report_task(
    project_id: str,
    task_id: str,
    user_instruction: str | None,
) -> None:
    """启动独立报告渲染后台任务。

    输入为研究项目编号、后台任务编号和可选展示要求；该任务只读取已落库的
    research_result 并生成 HTML 报告版本，不重新执行研究。
    """

    _send_task(
        task_path="research.render_report",
        task_name="render_report",
        project_id=project_id,
        task_id=task_id,
        args=(project_id, task_id, user_instruction),
    )


def _send_task(
    task_path: str,
    task_name: str,
    project_id: str,
    task_id: str,
    args: tuple[Any, ...],
) -> None:
    """把后台任务投递到 Celery 队列。

    输入为 Celery 任务路径、任务名称、项目编号和任务参数；输出为空。该函数隔离
    Celery 投递细节，保证 routers 层不直接依赖具体的后台任务启动方式。
    """

    from app.celery_app import celery_app

    celery_app.send_task(task_path, args=args)
    logger.info(
        "后台任务已投递到 Celery，task_name={}，project_id={}，task_id={}",
        task_name,
        project_id,
        task_id,
    )


async def run_generate_research_brief_task(project_id: str, task_id: str) -> None:
    """执行研究任务书和大纲生成任务。

    输入为项目编号和任务编号；执行过程会读取研究项目、调用研究管理智能体生成
    任务书与大纲，并把结果保存到 repository。该函数不处理 HTTP 响应。
    """

    try:
        await research_task_repository.mark_task_running(
            task_id=task_id,
            message="正在生成研究任务书和大纲",
        )
        await research_project_repository.update_project_status(
            project_id=project_id,
            status=ProjectStatus.BRIEF_GENERATING,
        )
        logger.info("开始生成研究任务书和大纲，project_id={}，task_id={}", project_id, task_id)

        project = await research_project_repository.get_project(project_id=project_id)
        research_agent = get_research_agent()
        result = await research_agent.generate_research_brief(project=project)

        await research_project_repository.save_research_brief_and_outline(
            project_id=project_id,
            research_brief=result.research_brief,
            outline=result.outline,
        )
        await research_project_repository.update_project_status(
            project_id=project_id,
            status=ProjectStatus.OUTLINE_READY,
        )
        await research_task_repository.mark_task_succeeded(
            task_id=task_id,
            message="研究任务书和大纲已生成，等待用户确认",
        )
        logger.info("研究任务书和大纲生成完成，project_id={}，task_id={}", project_id, task_id)
    except Exception as exc:
        await _mark_task_failed(
            project_id=project_id,
            task_id=task_id,
            message="研究任务书和大纲生成失败",
            exc=exc,
        )
        raise


async def run_revise_outline_task(
    project_id: str,
    task_id: str,
    revision_instruction: str,
) -> None:
    """执行研究大纲修改任务。

    输入为项目编号、任务编号和用户修改要求；执行过程会读取当前大纲，调用研究管理
    智能体产出修订版大纲，并保存回项目记录。
    """

    try:
        await research_task_repository.mark_task_running(
            task_id=task_id,
            message="正在根据用户要求修改研究大纲",
        )
        await research_project_repository.update_project_status(
            project_id=project_id,
            status=ProjectStatus.OUTLINE_REVISING,
        )
        logger.info("开始修改研究大纲，project_id={}，task_id={}", project_id, task_id)

        project = await research_project_repository.get_project(project_id=project_id)
        outline = await research_project_repository.get_outline(project_id=project_id)
        research_agent = get_research_agent()
        revised_outline = await research_agent.revise_outline(
            project=project,
            outline=outline,
            revision_instruction=revision_instruction,
        )

        await research_project_repository.save_outline(
            project_id=project_id,
            outline=revised_outline,
        )
        await research_project_repository.update_project_status(
            project_id=project_id,
            status=ProjectStatus.OUTLINE_READY,
        )
        await research_task_repository.mark_task_succeeded(
            task_id=task_id,
            message="研究大纲已修改，等待用户确认",
        )
        logger.info("研究大纲修改完成，project_id={}，task_id={}", project_id, task_id)
    except Exception as exc:
        await _mark_task_failed(
            project_id=project_id,
            task_id=task_id,
            message="研究大纲修改失败",
            exc=exc,
        )
        raise


async def run_generate_report_task(
    project_id: str,
    task_id: str,
    user_instruction: str | None,
) -> None:
    """执行研究报告生成任务。

    输入为项目编号、任务编号和可选的报告生成要求；执行过程会读取已确认大纲，
    先调用研究管理智能体完成研究结果落库，再调用确定性报告渲染流程生成 HTML。
    """

    try:
        await research_task_repository.mark_task_running(
            task_id=task_id,
            message="正在执行研究并生成报告",
        )
        await research_project_repository.update_project_status(
            project_id=project_id,
            status=ProjectStatus.RESEARCH_RUNNING,
        )
        logger.info("开始执行研究和报告渲染，project_id={}，task_id={}", project_id, task_id)

        project = await research_project_repository.get_project(project_id=project_id)
        outline = await research_project_repository.get_confirmed_outline(project_id=project_id)
        research_agent = get_research_agent()

        research_result = await research_agent.generate_research_result(
            project=project,
            outline=outline,
            user_instruction=user_instruction,
        )
        await research_project_repository.save_research_result(
            project_id=project_id,
            research_result=research_result,
        )
        logger.info(
            "研究结果已保存，project_id={}，task_id={}，sections={}",
            project_id,
            task_id,
            len(research_result.sections),
        )

        project_with_research_result = await research_project_repository.get_project(
            project_id=project_id
        )
        result = await research_agent.generate_report(
            project=project_with_research_result,
            outline=outline,
            user_instruction=user_instruction,
        )
        await report_repository.save_report_version(
            project_id=project_id,
            title=result.title,
            html=result.html,
            sources=result.sources,
        )
        await research_project_repository.update_project_status(
            project_id=project_id,
            status=ProjectStatus.REPORT_READY,
        )
        await research_task_repository.mark_task_succeeded(
            task_id=task_id,
            message="研究报告已生成",
        )
        logger.info("研究和报告渲染完成，project_id={}，task_id={}", project_id, task_id)
    except Exception as exc:
        await _mark_task_failed(
            project_id=project_id,
            task_id=task_id,
            message="研究报告生成失败",
            exc=exc,
        )
        raise


async def run_render_report_task(
    project_id: str,
    task_id: str,
    user_instruction: str | None,
) -> None:
    """执行独立报告渲染任务。

    输入为项目编号、任务编号和可选展示要求；执行过程只读取已保存的 research_result，
    调用确定性报告渲染流程生成 HTML 并保存报告版本，不触发主研究智能体。
    """

    try:
        await research_task_repository.mark_task_running(
            task_id=task_id,
            message="正在基于已有研究结果渲染报告",
        )
        logger.info("开始独立渲染报告，project_id={}，task_id={}", project_id, task_id)

        project = await research_project_repository.get_project(project_id=project_id)
        if not isinstance(project, dict) or not project.get("research_result"):
            raise ValueError("项目缺少已落库的 research_result，无法直接渲染报告")

        outline = await research_project_repository.get_confirmed_outline(project_id=project_id)
        research_agent = get_research_agent()
        result = await research_agent.generate_report(
            project=project,
            outline=outline,
            user_instruction=user_instruction,
        )
        await report_repository.save_report_version(
            project_id=project_id,
            title=result.title,
            html=result.html,
            sources=result.sources,
        )
        await research_project_repository.update_project_status(
            project_id=project_id,
            status=ProjectStatus.REPORT_READY,
        )
        await research_task_repository.mark_task_succeeded(
            task_id=task_id,
            message="报告已基于已有研究结果生成",
        )
        logger.info("独立报告渲染完成，project_id={}，task_id={}", project_id, task_id)
    except Exception as exc:
        await _mark_task_failed(
            project_id=project_id,
            task_id=task_id,
            message="独立报告渲染失败",
            exc=exc,
        )
        raise


async def _mark_task_failed(
    project_id: str,
    task_id: str,
    message: str,
    exc: Exception,
) -> None:
    """统一记录后台任务失败状态。

    输入为项目编号、任务编号、业务失败说明和异常对象；输出为空。该函数只写入必要
    的错误摘要和日志，不输出 API Key、访问令牌或用户隐私原文。
    """

    error_message = _build_task_error_message(message=message, exc=exc)
    logger.exception(
        "后台任务执行失败，project_id={}，task_id={}，error={}，exception_detail={}，exception_attrs={}",
        project_id,
        task_id,
        error_message,
        str(exc),
        _extract_exception_attrs(exc),
    )
    await research_task_repository.mark_task_failed(
        task_id=task_id,
        message=error_message,
    )


def _build_task_error_message(message: str, exc: Exception) -> str:
    """构建写入任务状态的短错误摘要。"""

    detail = str(exc).strip()
    if detail:
        return f"{message}: {type(exc).__name__}: {detail[:500]}"
    return f"{message}: {type(exc).__name__}"


def _extract_exception_attrs(exc: Exception) -> dict[str, Any]:
    """提取常见 LLM/HTTP 异常字段，便于定位 BadRequestError。"""

    attrs: dict[str, Any] = {}
    for name in (
        "status_code",
        "code",
        "type",
        "param",
        "request_id",
        "body",
        "response",
        "message",
    ):
        if not hasattr(exc, name):
            continue
        value = getattr(exc, name)
        attrs[name] = _safe_repr(value)
    if getattr(exc, "args", None):
        attrs["args"] = _safe_repr(exc.args)
    if getattr(exc, "__dict__", None):
        attrs["dict"] = _safe_repr(exc.__dict__)
    return attrs


def _safe_repr(value: Any, max_length: int = 4000) -> str:
    """返回适合日志记录的短文本表示。"""

    text = repr(value)
    if len(text) > max_length:
        return text[:max_length] + "...<truncated>"
    return text
