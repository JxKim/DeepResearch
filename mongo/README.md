# MongoDB本地部署

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