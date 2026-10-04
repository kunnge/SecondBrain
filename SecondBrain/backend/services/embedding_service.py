
from pathlib import Path

from sentence_transformers import SentenceTransformer

# 作用：文本 → 向量

# Embedding 模型服务类
class EmbeddingService:
    def __init__(self):
        # 获取项目根目录
        BASE_DIR = Path(__file__).resolve().parent.parent
        # 本地模型保存路径
        self.model_path = BASE_DIR / "models" / "bge-small-zh-v1.5"
        # 加载模型
        if self.model_path.exists():
            print("加载本地Embedding模型")
            self.embedding_model = SentenceTransformer(str(self.model_path))
        else:
            print("下载Embedding模型")
            self.embedding_model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
            print("模型下载完成")
            # 保存模型到本地
            self.embedding_model.save(str(self.model_path))
    def embed_documents(self,texts:list[str]) -> list[list[float]]:
        """
            文档批量向量化：用于入库
        """
        vectors = self.embedding_model.encode(texts,normalize_embeddings=True)
        return vectors.tolist()
    def embed_query(self,text:str) -> list[float]:
        """
            用户问题向量化：用于检索
        """
        query = ("为这个句子生成表示以用于检索相关文章："+ text)
        vector = self.embedding_model.encode(query,normalize_embeddings=True)
        return vector.tolist()

embedding_service = EmbeddingService()