## 启动Redis镜像

可通过如下命令，启动redis镜像：
```bash
docker run -d \
    --name deep-research-redis \
    -p 6379:6379 \
    docker.m.daocloud.io/library/redis:7.2
```