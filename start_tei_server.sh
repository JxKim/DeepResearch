#!/bin/bash

# 配置部分
# --------------------------------------------------
# 模型挂载目录（宿主机路径）
MODEL_VOLUME="/home/m1881/pycharm_projects/DeepResearch/data"



# Embedding 模型配置
EMBEDDING_MODEL_ID="/data/models--BAAI--bge-m3/snapshots/5617a9f61b028005a4858fdac845db406aefb181"  # 使用本地挂载的模型路径
EMBEDDING_PORT=8080
EMBEDDING_CONTAINER_NAME="ragflow_embedding"

# Reranker 模型配置
# RERANKER_MODEL_ID="BAAI/bge-reranker-v2-m3" # 使用本地挂载的模型路径
# RERANKER_PORT=8081
# RERANKER_CONTAINER_NAME="ragflow_reranker"





echo "=================================================="
echo "准备启动 Text Embeddings Inference (TEI) 服务..."
echo "模型挂载目录: $MODEL_VOLUME"
echo "=================================================="

# 1. 启动 Embedding 服务
echo ""
echo "启动 Embedding 服务 ($EMBEDDING_MODEL_ID)..."



# 此处使用社区镜像，官方镜像对于Blackwell 架构GPU不支持 具体参考https://github.com/huggingface/text-embeddings-inference/pull/735
docker run --gpus all -p $EMBEDDING_PORT:80 -v "$MODEL_VOLUME":/data --name $EMBEDDING_CONTAINER_NAME -d \
    hotchpotch/tei-blackwell-testing --model-id $EMBEDDING_MODEL_ID --auto-truncate

if [ $? -eq 0 ]; then
    echo "✅ Embedding 服务启动成功！"
    echo "   地址: http://localhost:$EMBEDDING_PORT"
else
    echo "❌ Embedding 服务启动失败，请检查日志: docker logs $EMBEDDING_CONTAINER_NAME"
fi

# # 2. 启动 Reranker 服务
# echo ""
# echo "[2/2] 启动 Reranker 服务 ($RERANKER_MODEL_ID)..."


# docker run --gpus all -p $RERANKER_PORT:80 -v "$MODEL_VOLUME":/data --pull always --name $RERANKER_CONTAINER_NAME -d \
#     hotchpotch/tei-blackwell-testing --model-id $RERANKER_MODEL_ID --auto-truncate

# if [ $? -eq 0 ]; then
#     echo "✅ Reranker 服务启动成功！"
#     echo "   地址: http://localhost:$RERANKER_PORT"
# else
#     echo "❌ Reranker 服务启动失败，请检查日志: docker logs $RERANKER_CONTAINER_NAME"
# fi

# echo ""
# echo "=================================================="
# echo "服务状态概览:"
# docker ps -f name=agent_embedding
# docker ps -f name=agent_reranker
# echo "=================================================="
