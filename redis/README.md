## 启动 Redis 镜像

推荐直接使用项目根目录的 `docker-compose.yml` 启动：

```bash
docker compose up -d redis
```

该服务默认启用密码：

```text
infini_rag_flow
```

项目连接串：

```env
REDIS_URL=redis://:infini_rag_flow@localhost:6379/0
CELERY_BROKER_URL=redis://:infini_rag_flow@localhost:6379/0
```

也可以手动启动 Redis：

```bash
docker run -d \
    --name deep-research-redis \
    -p 6379:6379 \
    docker.m.daocloud.io/library/redis:7.2 \
    redis-server --requirepass infini_rag_flow --appendonly yes
```

如果本机已经有其他 Redis 占用 `6379`，不要再启动 `deep-research-redis`。复用已有 Redis 即可，但需要把 `.env` 中的 `REDIS_URL` 和 `CELERY_BROKER_URL` 改成实际地址和密码。
