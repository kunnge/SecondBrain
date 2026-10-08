from fastapi import APIRouter
from pydantic import BaseModel
from rag.retriever import retriever
from services.embedding_service import embedding_service
router = APIRouter(prefix="/evaluation")
class RetrievalRequest(BaseModel):
    """Retrieval 测试请求参数"""
    query: str
    document_id: str | None = None
    child_top_k: int = 12
    parent_top_k: int = 4
@router.post("/retrieval")
def retrieval(request: RetrievalRequest):
    """测试完整 Retrieval 流程"""
    # 将用户 Query 转换成向量
    query_vector = embedding_service.embed_query(request.query)
    # 执行完整 Retrieval：Vector + BM25 + RRF + Parent 去重 + Reranker
    results = retriever.search(
        query=request.query,
        vector=query_vector,
        child_top_k=request.child_top_k,
        parent_top_k=request.parent_top_k,
        document_id=request.document_id,
        evaluation=True
    )
    # 返回 Retrieval 测试结果
    return {
        "query": request.query,
        "document_id": request.document_id,
        "child_top_k": request.child_top_k,
        "parent_top_k": request.parent_top_k,
        "count": len(results),
        "results": results
    }