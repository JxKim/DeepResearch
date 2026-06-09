"""
用于定义所有的routers，及routers当中所有的路由函数
"""
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from loguru import logger

from app.background.research_tasks import (
    start_generate_report_task,
    start_generate_research_brief_task,
    start_render_report_task,
    start_revise_outline_task,
)
from app.repository import report_repository, research_project_repository, research_task_repository
from app.schemas import (
    LatestReportResponse,
    NextStep,
    OutlineAction,
    OutlineConfirmResponse,
    OutlineResponse,
    OutlineRevisionResponse,
    OutlineUpdateRequest,
    ProjectStatus,
    ReportTaskCreate,
    ReportTaskCreateResponse,
    ResearchProjectCreate,
    ResearchProjectCreateResponse,
    TaskStatus,
    TaskStatusResponse,
    TaskType,
    utc_now,
)

router = APIRouter(tags=["研究项目"])


async def _create_task(project_id: str, task_type: TaskType, message: str) -> TaskStatusResponse:
    """创建后台任务状态记录。

    输入项目编号、任务类型和状态说明，输出任务状态响应对象。该函数只委托
    repository 持久化任务，不在路由层保存任何进程内状态。
    """

    now = utc_now()
    return await research_task_repository.create_task(
        task_id=str(uuid4()),
        project_id=project_id,
        task_type=task_type,
        status=TaskStatus.QUEUED,
        message=message,
        created_at=now,
        updated_at=now,
    )


async def _get_project(project_id: str) -> dict[str, object]:
    """根据项目编号从 repository 读取项目记录，不存在时返回 404 错误。"""

    project = await research_project_repository.get_project(project_id=project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="研究项目不存在")
    return project


@router.post(
    "/research-projects",
    response_model=ResearchProjectCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_research_project(
    request: ResearchProjectCreate,
) -> ResearchProjectCreateResponse:
    """创建研究项目，并生成初始大纲任务记录。

    输入为用户提交的研究主题和基础设定，输出为项目编号、初始任务编号和当前状态。
    当前版本不直接执行 Agent 长任务，只为后续 background 模块保留接口契约。
    """

    project_id = str(uuid4())
    created_at = utc_now()
    task = await _create_task(
        project_id=project_id,
        task_type=TaskType.GENERATE_RESEARCH_BRIEF,
        message="研究任务书和大纲生成任务已创建",
    )
    await research_project_repository.create_project(
        project_id=project_id,
        request=request,
        topic=request.topic,
        status=ProjectStatus.BRIEF_GENERATING,
        created_at=created_at,
    )
    start_generate_research_brief_task(project_id=project_id, task_id=task.task_id)
    logger.info("创建研究项目成功，project_id={}，initial_task_id={}", project_id, task.task_id)
    return ResearchProjectCreateResponse(
        project_id=project_id,
        initial_task_id=task.task_id,
        initial_task_type=TaskType.GENERATE_RESEARCH_BRIEF,
        topic=request.topic,
        status=ProjectStatus.BRIEF_GENERATING,
        next_step=NextStep.WAIT_FOR_OUTLINE,
        created_at=created_at,
    )


@router.get("/research-projects/{project_id}/outline", response_model=OutlineResponse)
async def get_outline(project_id: str) -> OutlineResponse:
    """获取研究项目的大纲草案。

    输入为项目编号，输出为项目当前状态和大纲节点列表。大纲不存在时返回空列表，
    不在路由层触发任何长任务。
    """

    project = await _get_project(project_id)
    outline = await research_project_repository.get_outline(project_id=project_id)
    return OutlineResponse(
        project_id=project_id,
        status=project["status"],  # type: ignore[arg-type]
        outline=outline if isinstance(outline, list) else [],
    )


@router.put(
    "/research-projects/{project_id}/outline",
    response_model=OutlineConfirmResponse | OutlineRevisionResponse,
)
async def update_outline(
    project_id: str,
    request: OutlineUpdateRequest,
) -> OutlineConfirmResponse | OutlineRevisionResponse:
    """保存用户对大纲的确认或修改请求。

    输入为项目编号和大纲操作请求；确认时直接更新项目状态，修改时创建大纲修改任务。
    当前版本用临时任务记录表达修改动作，后续接入 Agent 后替换实际修改逻辑。
    """

    await _get_project(project_id)
    if request.action == OutlineAction.CONFIRM:
        outline = await research_project_repository.get_outline(project_id=project_id)
        if not outline:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="当前研究项目尚未生成可确认的大纲",
            )
        await research_project_repository.save_confirmed_outline(
            project_id=project_id,
            outline=outline,
        )
        await research_project_repository.update_project_status(
            project_id=project_id,
            status=ProjectStatus.OUTLINE_CONFIRMED,
        )
        logger.info("研究大纲已确认，project_id={}", project_id)
        return OutlineConfirmResponse(
            project_id=project_id,
            status=ProjectStatus.OUTLINE_CONFIRMED,
            next_step=NextStep.GENERATE_REPORT,
        )

    task = await _create_task(
        project_id=project_id,
        task_type=TaskType.REVISE_OUTLINE,
        message="大纲修改任务已创建",
    )
    await research_project_repository.update_project_status(
        project_id=project_id,
        status=ProjectStatus.OUTLINE_REVISING,
    )
    start_revise_outline_task(
        project_id=project_id,
        task_id=task.task_id,
        revision_instruction=request.revision_instruction or "",
    )
    logger.info("研究大纲修改任务已创建，project_id={}，task_id={}", project_id, task.task_id)
    return OutlineRevisionResponse(
        project_id=project_id,
        revision_task_id=task.task_id,
        status=ProjectStatus.OUTLINE_REVISING,
        next_step=NextStep.WAIT_FOR_OUTLINE,
    )


@router.post(
    "/research-projects/{project_id}/report-tasks",
    response_model=ReportTaskCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_report_task(
    project_id: str,
    request: ReportTaskCreate,
) -> ReportTaskCreateResponse:
    """提交报告生成任务。

    输入为项目编号和可选报告要求，输出为报告生成任务编号。只有已确认大纲的项目
    可以提交报告任务，避免跳过第一版要求的人工介入点。
    """

    project = await _get_project(project_id)
    if project["status"] != ProjectStatus.OUTLINE_CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先确认研究大纲，再提交报告生成任务",
        )

    task = await _create_task(
        project_id=project_id,
        task_type=TaskType.GENERATE_REPORT,
        message=request.user_instruction or "报告生成任务已创建",
    )
    await research_project_repository.update_project_status(
        project_id=project_id,
        status=ProjectStatus.RESEARCH_RUNNING,
    )
    start_generate_report_task(
        project_id=project_id,
        task_id=task.task_id,
        user_instruction=request.user_instruction,
    )
    logger.info("报告生成任务已创建，project_id={}，task_id={}", project_id, task.task_id)
    return ReportTaskCreateResponse(
        task_id=task.task_id,
        project_id=project_id,
        task_type=TaskType.GENERATE_REPORT,
        status=TaskStatus.QUEUED,
    )


@router.post(
    "/research-projects/{project_id}/report-render-tasks",
    response_model=ReportTaskCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_report_render_task(
    project_id: str,
    request: ReportTaskCreate,
) -> ReportTaskCreateResponse:
    """提交独立报告渲染任务。

    输入为项目编号和可选报告展示要求，输出为报告渲染任务编号。该接口只基于已经
    落库的 research_result 调用确定性报告渲染流程，不重新执行研究。
    """

    project = await _get_project(project_id)
    if not project.get("research_result"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="当前研究项目尚未生成研究结果，无法直接渲染报告",
        )

    task = await _create_task(
        project_id=project_id,
        task_type=TaskType.RENDER_REPORT,
        message=request.user_instruction or "报告渲染任务已创建",
    )
    start_render_report_task(
        project_id=project_id,
        task_id=task.task_id,
        user_instruction=request.user_instruction,
    )
    logger.info("报告渲染任务已创建，project_id={}，task_id={}", project_id, task.task_id)
    return ReportTaskCreateResponse(
        task_id=task.task_id,
        project_id=project_id,
        task_type=TaskType.RENDER_REPORT,
        status=TaskStatus.QUEUED,
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse, tags=["后台任务"])
async def get_task(task_id: str) -> TaskStatusResponse:
    """查询后台任务状态。

    输入为任务编号，输出为任务类型、状态、说明和更新时间；任务不存在时返回 404。
    """

    task = await research_task_repository.get_task(task_id=task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="后台任务不存在")
    return task


@router.get(
    "/research-projects/{project_id}/reports/latest",
    response_model=LatestReportResponse,
    tags=["研究报告"],
)
async def get_latest_report(project_id: str) -> LatestReportResponse:
    """获取指定研究项目的最新报告。

    输入为项目编号，输出为最新 HTML 报告、版本号和来源列表；报告不存在时返回 404。
    """

    await _get_project(project_id)
    report = await report_repository.get_latest_report(project_id=project_id)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="研究报告不存在")
    return report
