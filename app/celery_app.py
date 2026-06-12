from celery import Celery

from app.config.config import Settings, get_settings


def create_celery_app() -> Celery:
    """创建 Celery 应用实例，供 API 进程投递任务和 worker 进程消费任务。"""

    settings: Settings = get_settings()
    app = Celery(
        "deep_research",
        broker=settings.celery_broker_url or settings.redis_url,
        # backend="",
        include=["app.background.celery_tasks"],
    )

    app.conf.update(
        broker_connection_retry_on_startup=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        worker_prefetch_multiplier=1,
        timezone="Asia/Shanghai",
    )
    return app


celery_app = create_celery_app()
