# from modelscope import snapshot_download
# snapshot_download("BAAI/bge-m3",cache_dir="./data")

from huggingface_hub import snapshot_download

snapshot_download("BAAI/bge-reranker-v2-m3",cache_dir="./data")