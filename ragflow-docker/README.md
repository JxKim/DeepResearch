# RAGFlow 本地 Docker 部署

该目录用于在当前项目内持久化部署 RAGFlow。

## 目录说明

- `docker-compose.yml`：RAGFlow 主服务编排。
- `docker-compose-base.yml`：MySQL、Elasticsearch、MinIO、Redis、TEI 等基础服务编排。
- `.env`：端口、镜像、密码、TEI 模型路径等运行配置。
- `entrypoint.sh`：RAGFlow 容器启动脚本。
- `init.sql`：MySQL 初始化 SQL。
- `service_conf.yaml.template`：RAGFlow 服务配置模板。
- `storage/`：MySQL、Elasticsearch、MinIO、Redis 等持久化数据。
- `ragflow-logs/`：RAGFlow 运行日志。

`storage/` 和 `ragflow-logs/` 已在本目录 `.gitignore` 中忽略，不会提交到 Git。

## 当前关键配置

当前配置默认使用：

- RAGFlow 镜像：`swr.cn-north-4.myhuaweicloud.com/infiniflow/ragflow:v0.25.6`
- TEI 镜像：`hotchpotch/tei-blackwell-testing`
- TEI 模型目录：`../data/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181`
- TEI 端口：`6380`
- MySQL 对外端口：`5455`
- RAGFlow Web 端口：`80`
- RAGFlow API 端口：`9380`

TEI 使用 Blackwell 兼容镜像，不使用官方 compose 里默认的 `tei-cpu` / `tei-gpu` 服务。

## 启动前检查

在项目根目录执行：

```bash
docker compose -f ragflow-docker/docker-compose.yml config --quiet
```

没有输出表示 compose 配置可以正常解析。

确认本地模型目录存在：

```bash
ls data/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181
```

## 启动服务

在项目根目录执行：

```bash
docker compose -f ragflow-docker/docker-compose.yml up -d
```

查看容器状态：

```bash
docker compose -f ragflow-docker/docker-compose.yml ps
```

等待以下服务变为 `healthy` 或正常 `Up`：

- `tei`
- `mysql`
- `es01`
- `minio`
- `redis`
- `ragflow-cpu`

## 健康检查

测试 TEI：

```bash
curl -i http://127.0.0.1:6380/health
```

测试 RAGFlow Web：

```bash
curl -i http://127.0.0.1/
```

测试 RAGFlow API 端口：

```bash
curl -i http://127.0.0.1:9380
```

从 RAGFlow 容器内部测试是否能访问 TEI：

```bash
docker compose -f ragflow-docker/docker-compose.yml exec -T ragflow-cpu curl -i http://tei:80/health
```

## 查看日志

查看 RAGFlow 主服务日志：

```bash
docker compose -f ragflow-docker/docker-compose.yml logs -f ragflow-cpu
```

查看 TEI 日志：

```bash
docker compose -f ragflow-docker/docker-compose.yml logs -f tei
```

查看 MySQL 日志：

```bash
docker compose -f ragflow-docker/docker-compose.yml logs -f mysql
```

## 停止和重启

停止服务：

```bash
docker compose -f ragflow-docker/docker-compose.yml stop
```

重新启动：

```bash
docker compose -f ragflow-docker/docker-compose.yml up -d
```

不要使用：

```bash
docker compose -f ragflow-docker/docker-compose.yml down -v
```

`down -v` 会删除 Docker volume。当前配置主要使用项目内 `storage/` 做持久化，但仍建议避免在未确认影响前执行带 `-v` 的删除命令。

## 常见问题

### RAGFlow 主服务或 MySQL 退出 127

如果错误类似：

```text
Are you trying to mount a directory onto a file (or vice-versa)?
```

通常说明 bind mount 的宿主机路径类型不对。之前把部署文件放在 `/tmp/ragflow-docker` 时，WSL 重启后文件丢失，Docker 自动把缺失路径创建成目录，导致 `entrypoint.sh`、`init.sql` 等文件挂载失败。

现在部署文件已经放在当前项目的 `ragflow-docker/` 下，可以避免这个问题。

### RAGFlow 无法连接 TEI

先检查 TEI 是否健康：

```bash
docker compose -f ragflow-docker/docker-compose.yml ps tei
curl -i http://127.0.0.1:6380/health
```

再从 RAGFlow 容器内部检查：

```bash
docker compose -f ragflow-docker/docker-compose.yml exec -T ragflow-cpu curl -i http://tei:80/health
```

如果宿主机可访问但容器内不可访问，优先检查 compose 网络和 `TEI_HOST=tei`。

### embedding batch size 报 413

如果日志中出现：

```text
batch size 16 > maximum allowed batch size 8
```

说明 RAGFlow 的 embedding 批大小大于 TEI 允许的客户端批大小。当前 `.env` 已设置：

```env
EMBEDDING_BATCH_SIZE=${EMBEDDING_BATCH_SIZE:-16}
TEI_MAX_CLIENT_BATCH_SIZE=16
```

如果后续调整 `EMBEDDING_BATCH_SIZE`，需要同步调整 `TEI_MAX_CLIENT_BATCH_SIZE`。

### TEI 被 OOM Kill

检查：

```bash
docker inspect --format 'oom={{.State.OOMKilled}} restart={{.RestartCount}}' ragflow-docker-tei-1
```

如果 `oom=true`，需要降低 TEI 并发参数，例如：

```env
TEI_TOKENIZATION_WORKERS=1
TEI_MAX_CONCURRENT_REQUESTS=8
TEI_MAX_BATCH_TOKENS=1024
```

修改 `.env` 后重启 TEI：

```bash
docker compose -f ragflow-docker/docker-compose.yml up -d --force-recreate tei
```
