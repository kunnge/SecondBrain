from db.database import db_manager
from retrieval.bm25_search import BM25Search
from retrieval.hybrid import HybridRetriever
from retrieval.reranker import Reranker
from retrieval.rrf import RRFFuser
from retrieval.vector_search import VectorSearch



class RAGRetriever:
    """RAG 检索器：统一管理 Vector、BM25、RRF、Reranker 和 HybridRetriever"""
    def __init__(self, engine):
        # 初始化向量检索器
        self.vector_search = VectorSearch(engine)
        # 初始化 BM25 检索器
        self.bm25_search = BM25Search(engine)
        # 初始化 RRF 融合器
        self.rrf_fuser = RRFFuser()
        # 初始化 Reranker 重排序器
        self.reranker = Reranker()
        # 将各个检索组件组合成完整的混合检索流程
        self.hybrid = HybridRetriever(
            engine=engine,
            vector_search=self.vector_search,
            bm25_search=self.bm25_search,
            rrf_fuser=self.rrf_fuser,
            reranker=self.reranker
        )
    """执行完整的 RAG 混合检索"""
    def search(self, query: str, vector: list[float], child_top_k: int = 12,parent_top_k: int = 4, document_id: str | None = None,evaluation: bool =False):
        # 调用 HybridRetriever 执行 Vector + BM25 + RRF + Parent 去重 + Reranker
        return self.hybrid.search( query=query, vector=vector, child_top_k=child_top_k, parent_top_k=parent_top_k, document_id=document_id,evaluation=evaluation)
    """重新加载数据库中的 Child Chunk 并刷新 BM25 索引"""
    def refresh_bm25_index(self):
        # 重新建立 BM25 索引，使新增或更新的 Chunk 可以参与检索
        self.bm25_search.refresh_bm25_index()
# 创建全局 RAG 检索器实例，使用数据库引擎连接 PostgreSQL
retriever = RAGRetriever(db_manager.engine)