# RAGFlow Docker 部署踩坑记录

记录时间：2026-06-07

本次目标是在本机通过 Docker 启动 RAGFlow，用于后续测试项目里的 `ragflow_search` 工具。

## 最终状态

RAGFlow 已启动成功。

访问地址：

```text
Web UI: http://127.0.0.1
API base: http://127.0.0.1:9380
```

当前使用的临时部署目录：

```bash
/tmp/ragflow-docker
```

当前启动方式：

```bash
cd /tmp/ragflow-docker
docker compose -f docker-compose.yml up -d
```

停止方式：

```bash
cd /tmp/ragflow-docker
docker compose -f docker-compose.yml down
```

## 本机环境检查

本机满足 RAGFlow 官方 Docker 部署的关键条件：

```text
Docker version 28.5.1
Docker Compose version v2.40.1
CPU arch: x86_64
vm.max_map_count = 1048576
```

RAGFlow 官方文档要求 `vm.max_map_count` 不小于 `262144`，本机已经满足。

## 坑 1：不要只拉 RAGFlow 单镜像手写启动

RAGFlow 不是单容器服务，默认依赖：

```text
RAGFlow server
MySQL
Elasticsearch
MinIO
Redis/Valkey
```

所以本次没有直接 `docker run infiniflow/ragflow`，而是使用官方 `docker-compose.yml` 和 `docker-compose-base.yml`。

## 坑 2：完整克隆官方仓库很慢

一开始尝试：

```bash
git clone https://github.com/infiniflow/ragflow.git /tmp/ragflow
git clone --depth 1 https://github.com/infiniflow/ragflow.git /tmp/ragflow-shallow
```

两次都很慢，工作区迟迟没有拿到 `docker/` 目录。

最终改为只下载 Docker 部署所需文件：

```bash
mkdir -p /tmp/ragflow-docker
cd /tmp/ragflow-docker

curl -fL https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/docker-compose.yml -o docker-compose.yml
curl -fL https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/docker-compose-base.yml -o docker-compose-base.yml
curl -fL https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/.env -o .env
curl -fL https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/entrypoint.sh -o entrypoint.sh
curl -fL https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/service_conf.yaml.template -o service_conf.yaml.template
curl -fL https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/init.sql -o init.sql
curl -fL https://raw.githubusercontent.com/infiniflow/ragflow/v0.25.6/docker/infinity_conf.toml -o infinity_conf.toml
chmod +x entrypoint.sh
```

## 坑 3：配置文件版本必须和镜像版本一致

第一次下载的是 `main` 分支的 Docker 配置文件，但镜像使用的是：

```text
infiniflow/ragflow:v0.25.6
```

启动后主容器不断重启，日志里出现：

```text
python3: can't open file '/ragflow/tools/scripts/mysql_migration.py': [Errno 2] No such file or directory
```

原因是 `main` 分支的 `entrypoint.sh` 和 `v0.25.6` 镜像内部文件结构不匹配。

处理方式：

```text
所有 docker 配置文件都改为从 tag v0.25.6 下载。
```

这个坑后续很重要：镜像用哪个版本，compose、entrypoint、service_conf 模板就应该用同一个版本 tag。

## 坑 4：Docker Hub 直连超时

执行官方默认拉取：

```bash
docker compose -f docker-compose.yml pull
```

失败：

```text
Get "https://registry-1.docker.io/v2/": context deadline exceeded
```

检查 Docker daemon 镜像源：

```bash
docker info --format '{{json .RegistryConfig.Mirrors}}'
```

返回：

```text
null
```

说明本机 Docker 没有配置 registry mirror。

由于当前用户没有免密 sudo：

```text
sudo: a password is required
```

所以没有直接修改 `/etc/docker/daemon.json` 和重启 Docker。

## 坑 5：RAGFlow 主镜像改用官方提示的华为云镜像

官方文档提示如果 Docker Hub 拉不下来，可以使用华为云或阿里云镜像。

本次成功拉取：

```bash
docker pull swr.cn-north-4.myhuaweicloud.com/infiniflow/ragflow:v0.25.6
```

然后修改 `/tmp/ragflow-docker/.env`：

```env
RAGFLOW_IMAGE=swr.cn-north-4.myhuaweicloud.com/infiniflow/ragflow:v0.25.6
```

## 坑 6：依赖镜像仍然需要单独处理

华为云镜像只解决 RAGFlow 主镜像，不解决 MySQL、Elasticsearch、MinIO、Valkey。

本次通过 DaoCloud 镜像代理拉取依赖，再打成本地 compose 需要的原始 tag：

```bash
docker pull docker.m.daocloud.io/library/mysql:8.0.39
docker pull docker.m.daocloud.io/library/elasticsearch:8.11.3
docker pull docker.m.daocloud.io/pgsty/minio:RELEASE.2026-03-25T00-00-00Z
docker pull docker.m.daocloud.io/valkey/valkey:8

docker tag docker.m.daocloud.io/library/mysql:8.0.39 mysql:8.0.39
docker tag docker.m.daocloud.io/library/elasticsearch:8.11.3 elasticsearch:8.11.3
docker tag docker.m.daocloud.io/pgsty/minio:RELEASE.2026-03-25T00-00-00Z pgsty/minio:RELEASE.2026-03-25T00-00-00Z
docker tag docker.m.daocloud.io/valkey/valkey:8 valkey/valkey:8
```

## 坑 7：宿主机 MySQL 端口冲突

本机已有容器占用宿主机 `3306`：

```text
mysql 0.0.0.0:3306->3306/tcp
```

RAGFlow 默认 `.env`：

```env
EXPOSE_MYSQL_PORT=3306
```

会和已有 MySQL 冲突。

处理方式是只修改宿主机暴露端口：

```env
EXPOSE_MYSQL_PORT=5455
```

容器内部还是 `3306`，RAGFlow 容器通过 Docker 网络访问 `mysql:3306`，不受影响。

## 坑 8：`9380 /` 返回 404 是正常现象

启动成功后：

```bash
curl -I http://127.0.0.1
```

返回：

```text
HTTP/1.1 200 OK
```

说明 Web UI 已经起来。

但：

```bash
curl http://127.0.0.1:9380
```

返回：

```text
404
```

这是正常的，因为 API server 的根路径 `/` 没有业务路由，不代表 API 服务没启动。

日志中确认：

```text
RAGFlow server is ready
Running on http://0.0.0.0:9380
```

## 坑 9：第一次启动需要等待初始化

第一次启动后，主服务不是马上 ready。日志会经历：

```text
Initializing database tables...
Database tables initialized.
Starting nginx...
Attempt to start RAGFlow server...
Starting data sync...
Attempt to start Admin python server...
Starting 1 task executor(s)...
RAGFlow server is ready
```

如果刚启动就请求，可能出现：

```text
curl: (56) Recv failure: Connection reset by peer
```

这通常只是服务还在初始化，等几十秒后再测。

## 当前容器和端口

最终 `docker compose ps` 结果概要：

```text
ragflow-cpu   80, 443, 9380-9384
mysql         host 5455 -> container 3306
es01          host 1200 -> container 9200
minio         host 9000-9001
redis         host 6379
```

## 后续建议

当前部署目录在 `/tmp/ragflow-docker`，适合本次临时测试，但不适合长期维护。

如果后续要稳定使用，建议：

```text
1. 把 /tmp/ragflow-docker 移到项目外的固定目录，例如 ~/services/ragflow-docker。
2. 固定使用 v0.25.6 tag，不要混用 main 分支配置。
3. 如果本机网络长期无法访问 Docker Hub，给 Docker daemon 配置 registry mirror。
4. 不要在生产环境使用官方默认密码。
5. 为项目 `.env` 配置 RAGFLOW_BASE_URL=http://127.0.0.1:9380。
```
