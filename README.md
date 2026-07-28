# Deep Research 教学项目

本项目用于教学演示多智能体研究报告生成流程，重点覆盖 DeepAgents、文件系统上下文管理、任务拆分、Celery 异步任务、MongoDB 持久化和确定性 HTML 渲染。

## 1. 本地依赖

- Python 3.12+
- Docker
- Docker Compose
- 可用的大模型 API Key
- 可选：Tavily API Key
- 可选：RAGFlow 服务和有效 API Key

## 2. 启动基础设施

项目根目录提供了 `docker-compose.yml`，用于启动本项目需要的 MongoDB 和 Redis：

```bash
docker compose up -d mongo redis
```

容器说明：

| 容器 | 端口 | 作用 |
| --- | --- | --- |
| `deep-research-mongo` | `27017` | 保存研究项目、任务状态和报告版本 |
| `deep-research-redis` | `6379` | Celery broker |

MongoDB 首次启动时会执行 [mongo/init-mongo.js](mongo/init-mongo.js)，创建应用数据库用户：

```text
database: deep_research
username: deepresearch
password: deepresearch_dev
```

Redis 启动时会启用密码：

```text
password: infini_rag_flow
```

如果本机已经有其他 Redis 占用了 `6379`，可以复用已有 Redis，只要 `.env` 中的 `REDIS_URL` 和 `CELERY_BROKER_URL` 写对即可。

## 3. 配置环境变量

复制示例配置：

```bash
cp .env.example .env
```

默认容器配置对应：

```env
MONGODB_URI=mongodb://deepresearch:deepresearch_dev@localhost:27017/deep_research?authSource=deep_research
MONGODB_DATABASE=deep_research
REDIS_URL=redis://:infini_rag_flow@localhost:6379/0
CELERY_BROKER_URL=redis://:infini_rag_flow@localhost:6379/0
```

然后配置模型和搜索服务：

```env
LLM_PROVIDER=deepseek
LLM_MODEL_NAME=deepseek-chat
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_API_KEY=sk-xxxx

TAVILY_API_KEY=tvly-xxxx
```

RAGFlow 是可选能力。没有可用 token 时，可以关闭：

```env
ENABLE_RAGFLOW=false
```

## 4. 启动应用

启动 FastAPI：

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

启动 Celery worker：

```bash
.venv/bin/celery -A app.celery_app:celery_app worker -l INFO -P solo
```

访问地址：

```text
http://127.0.0.1:8000
http://127.0.0.1:8000/api/v1/docs
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## 5. 验证

运行静态检查和测试：

```bash
.venv/bin/python -m ruff check app tests
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q app tests
```

完整端到端流程：

```text
创建研究项目
  -> 等待 brief/outline 任务完成
  -> 获取大纲
  -> 确认大纲
  -> 提交报告生成任务
  -> 等待报告任务完成
  -> 获取 latest report
```

核心接口：

| 接口 | 方法 | 作用 |
| --- | --- | --- |
| `/health` | `GET` | 健康检查 |
| `/api/v1/research-projects` | `POST` | 创建研究项目 |
| `/api/v1/tasks/{task_id}` | `GET` | 查询任务状态 |
| `/api/v1/research-projects/{project_id}/outline` | `GET` | 获取大纲 |
| `/api/v1/research-projects/{project_id}/outline` | `PUT` | 确认或修改大纲 |
| `/api/v1/research-projects/{project_id}/report-tasks` | `POST` | 生成研究报告 |
| `/api/v1/research-projects/{project_id}/report-render-tasks` | `POST` | 基于已有章节重新渲染报告 |
| `/api/v1/research-projects/{project_id}/reports/latest` | `GET` | 获取最新报告 |
