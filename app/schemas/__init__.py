"""
该模块用于定义所有接口的schema信息
"""
from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class RegionScope(StrEnum):
    """研究地域范围枚举，用于限制创建项目时可选择的地理边界。"""

    CHINA = "china"
    OVERSEAS = "overseas"
    GLOBAL = "global"


class TimeScopeType(StrEnum):
    """研究时间范围类型枚举，用于表达近年研究或不限制时间范围。"""

    RECENT_YEARS = "recent_years"
    UNLIMITED = "unlimited"


class ProjectStatus(StrEnum):
    """研究项目状态枚举，用于前端判断当前项目所处的主流程阶段。"""

    CREATED = "created"
    BRIEF_GENERATING = "brief_generating"
    OUTLINE_READY = "outline_ready"
    OUTLINE_REVISING = "outline_revising"
    OUTLINE_CONFIRMED = "outline_confirmed"
    RESEARCH_RUNNING = "research_running"
    REPORT_READY = "report_ready"
    COMPLETED = "completed"


class TaskStatus(StrEnum):
    """后台任务状态枚举，用于表示异步任务的执行进度和最终结果。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TaskType(StrEnum):
    """后台任务类型枚举，用于区分大纲生成、大纲修改和报告生成任务。"""

    GENERATE_RESEARCH_BRIEF = "generate_research_brief"
    REVISE_OUTLINE = "revise_outline"
    GENERATE_REPORT = "generate_report"
    RENDER_REPORT = "render_report"


class OutlineAction(StrEnum):
    """大纲操作枚举，用于区分直接确认和按自然语言指令修改大纲。"""

    CONFIRM = "confirm"
    REVISE = "revise"


class NextStep(StrEnum):
    """下一步操作枚举，用于给前端提供稳定的流程跳转提示。"""

    WAIT_FOR_OUTLINE = "wait_for_outline"
    GENERATE_REPORT = "generate_report"
    WAIT_FOR_REPORT = "wait_for_report"


class TimeScope(BaseModel):
    """研究时间范围结构，负责校验时间范围类型和近年数量之间的关系。"""

    type: TimeScopeType
    years: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def validate_years(self) -> "TimeScope":
        """校验 recent_years 必须提供 years，unlimited 不需要 years。"""

        if self.type == TimeScopeType.RECENT_YEARS and self.years is None:
            raise ValueError("time_scope.type 为 recent_years 时必须提供 years")
        return self


class ResearchProjectCreate(BaseModel):
    """创建研究项目请求结构，承载用户输入的研究主题和基础设定。"""

    topic: str = Field(min_length=2, max_length=200)
    research_goal: str = Field(min_length=2, max_length=500)
    target_audience: str = Field(min_length=2, max_length=100)
    region_scope: RegionScope
    time_scope: TimeScope


class ResearchProjectCreateResponse(BaseModel):
    """创建研究项目响应结构，返回项目编号、初始任务编号和后续动作。"""

    project_id: str
    initial_task_id: str
    initial_task_type: TaskType
    topic: str
    status: ProjectStatus
    next_step: NextStep
    created_at: datetime


class OutlineNode(BaseModel):
    """研究大纲节点结构，用于表示章节、核心问题和多级子章节。"""

    node_id: str
    title: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=300)
    description: str = Field(min_length=1, max_length=500)
    children: list["OutlineNode"] = Field(default_factory=list)


class OutlineResponse(BaseModel):
    """获取大纲响应结构，返回项目状态和当前可展示的大纲草案。"""

    project_id: str
    status: ProjectStatus
    outline: list[OutlineNode]


class OutlineUpdateRequest(BaseModel):
    """保存大纲请求结构，支持确认大纲或提交自然语言修改指令。"""

    action: OutlineAction
    revision_instruction: str | None = Field(default=None, min_length=2, max_length=1000)

    @model_validator(mode="after")
    def validate_revision_instruction(self) -> "OutlineUpdateRequest":
        """校验 revise 操作必须提供 revision_instruction。"""

        if self.action == OutlineAction.REVISE and not self.revision_instruction:
            raise ValueError("action 为 revise 时必须提供 revision_instruction")
        return self


class OutlineConfirmResponse(BaseModel):
    """大纲确认响应结构，返回确认后的项目状态和下一步操作。"""

    project_id: str
    status: ProjectStatus
    next_step: NextStep


class OutlineRevisionResponse(BaseModel):
    """大纲修改响应结构，返回修改任务编号和等待大纲完成的下一步提示。"""

    project_id: str
    revision_task_id: str
    status: ProjectStatus
    next_step: NextStep


class ReportTaskCreate(BaseModel):
    """创建报告生成任务请求结构，承载用户对报告风格的补充要求。"""

    user_instruction: str | None = Field(default=None, max_length=1000)


class ReportTaskCreateResponse(BaseModel):
    """创建报告生成任务响应结构，返回任务编号和初始任务状态。"""

    task_id: str
    project_id: str
    task_type: TaskType
    status: TaskStatus


class TaskStatusResponse(BaseModel):
    """任务状态响应结构，用于前端轮询后台任务执行进度。"""

    task_id: str
    project_id: str
    task_type: TaskType
    status: TaskStatus
    message: str
    created_at: datetime
    updated_at: datetime


class ReportSource(BaseModel):
    """报告来源结构，用于保存可追溯的公开网页或内部知识库引用。"""

    source_id: str | None = None
    title: str
    url: str | None = None
    published_at: str | None = None
    source_type: str


class LatestReportResponse(BaseModel):
    """最新报告响应结构，返回 HTML 报告正文、版本号和来源列表。"""

    project_id: str
    report_id: str
    version: int
    title: str
    html: str
    sources: list[ReportSource]
    created_at: datetime


def utc_now() -> datetime:
    """返回 UTC 当前时间，统一接口响应和任务状态中的时间格式。"""

    return datetime.now(timezone.utc)
