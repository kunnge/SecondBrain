# rag/embedding.py
from sentence_transformers import SentenceTransformer

class EmbeddingService:
    def __init__(self):
        # 初始化时加载本地 Embedding 模型（建议作为类的属性，避免每次上传都重新加载模型）
        self.embedding_model = SentenceTransformer('BAAI/bge-small-zh-v1.5')

    def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        批量将文本列表转为向量
        """
        # encode 方法原生支持批量处理，速度极快
        embeddings = self.embedding_model.encode(texts, normalize_embeddings=True)
        # 将 numpy 数组转为 Python 的 list，方便后续存入数据库
        return embeddings.tolist()