import os
import torch
from sentence_transformers import CrossEncoder
from config.settings import RERANKER_BATCH_SIZE, RERANKER_MAX_LENGTH, RERANKER_MODEL_PATH

# 重排序器
class RerankerService:
    def __init__(self, model_path: str,max_length: int = RERANKER_MAX_LENGTH, batch_size: int = RERANKER_BATCH_SIZE):
        self.model_path = model_path
        self.max_length = max_length
        self.batch_size = batch_size
        # 有 NVIDIA GPU 就使用 CUDA
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"加载 Reranker: {model_path}")
        self.model = CrossEncoder( model_path,max_length=max_length,device=self.device)

    """ Query + Documents ->  Cross Encoder -> Reranker Score ->  排序 -> Top-K """
    def rerank(self,query: str,documents: list[str], top_k: int):

        if not documents:
            return []
        # Query 和每个 Parent 组成一对
        pairs = [[query, document]for document in documents]
        # 批量计算相关性分数
        scores = self.model.predict(pairs,batch_size=self.batch_size, show_progress_bar=False)
        results = [{"index": index,"score": float(score)}for index, score in enumerate(scores)]
        # 分数越高越相关
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

# 你的本地模型路径
MODEL_PATH = RERANKER_MODEL_PATH

reranker_service = RerankerService(model_path=MODEL_PATH,max_length=RERANKER_MAX_LENGTH,batch_size=RERANKER_BATCH_SIZE)
