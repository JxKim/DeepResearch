# MongoDB 本地部署

推荐直接使用项目根目录的 `docker-compose.yml` 启动：

```bash
docker compose up -d mongo
```

首次启动时，MongoDB 会执行 [init-mongo.js](init-mongo.js)，创建应用数据库用户：

```text
database: deep_research
username: deepresearch
password: deepresearch_dev
```

项目连接串：

```env
MONGODB_URI=mongodb://deepresearch:deepresearch_dev@localhost:27017/deep_research?authSource=deep_research
MONGODB_DATABASE=deep_research
```

如果你已经有一个无鉴权的本地 MongoDB，也可以使用：

```env
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=deep_research
```

## 手动构建镜像

从项目根目录构建：

```bash
docker build -f mongo/Dockerfile.mongodb -t deep-research-mongo:7.0 mongo
```


运行（无鉴权，本地开发）：

```bash
docker run -d --name deep-research-mongo \
     -p 27017:27017 \
     -v deep-research-mongo-data:/data/db \
     deep-research-mongo:7.0
```

无鉴权方式连接：

```text
mongodb://localhost:27017
```
