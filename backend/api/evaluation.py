from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from config.settings import (
    CONTEXT_MAX_CHUNKS_PER_PARENT,
    CONTEXT_MAX_TOTAL_CHUNKS,
    CONTEXT_NEIGHBOR_WINDOW,
    RETRIEVAL_CHILD_TOP_K,
    RETRIEVAL_PARENT_TOP_K,
    RERANK_MIN_PARENT_K,
    RERANK_PARENT_MULTIPLIER,
)
from rag.retriever import retriever
from services.embedding_service import embedding_service
from services.reranker_service import reranker_service
from evaluation.tuning.snapshot import get_retrieval_snapshot
"""Retrieval 测试请求参数"""
class RetrievalRequest(BaseModel):
    query: str
    document_id: str | None = None
    child_top_k: int = Field(default=RETRIEVAL_CHILD_TOP_K, ge=1, le=100)
    parent_top_k: int = Field(default=RETRIEVAL_PARENT_TOP_K, ge=1, le=20)
    rrf_k: int | None = Field(default=None, ge=1, le=1000)
    rerank_min_parent_k: int | None = Field(default=None, ge=1, le=100)
    rerank_parent_multiplier: int | None = Field(default=None, ge=1, le=20)
    reranker_candidates: int | None = Field(default=None, ge=1, le=100)
    context_neighbor_window: int | None = Field(default=None, ge=0, le=5)
    context_max_chunks_per_parent: int | None = Field(default=None, ge=1, le=20)
    context_max_total_chunks: int | None = Field(default=None, ge=1, le=100)



router = APIRouter(prefix="/evaluation")


@router.get("/snapshot")
def retrieval_snapshot():
    return get_retrieval_snapshot(
        retriever.hybrid.engine,
        retriever,
        embedding_service,
        reranker_service,
    )

"""测试完整 Retrieval 流程"""
@router.post("/retrieval")
def retrieval(request: RetrievalRequest):
    if request.reranker_candidates is not None and not (
        request.parent_top_k <= request.reranker_candidates <= request.child_top_k
    ):
        raise HTTPException(
            status_code=422,
            detail="reranker_candidates must be between parent_top_k and child_top_k",
        )
    effective_parameters = {
        "rerank_min_parent_k": request.rerank_min_parent_k if request.rerank_min_parent_k is not None else RERANK_MIN_PARENT_K,
        "rerank_parent_multiplier": request.rerank_parent_multiplier if request.rerank_parent_multiplier is not None else RERANK_PARENT_MULTIPLIER,
        "rrf_k": request.rrf_k if request.rrf_k is not None else retriever.rrf_fuser.RRF_K,
        "reranker_candidates": request.reranker_candidates,
        "context_neighbor_window": request.context_neighbor_window if request.context_neighbor_window is not None else CONTEXT_NEIGHBOR_WINDOW,
        "context_max_chunks_per_parent": request.context_max_chunks_per_parent if request.context_max_chunks_per_parent is not None else CONTEXT_MAX_CHUNKS_PER_PARENT,
        "context_max_total_chunks": request.context_max_total_chunks if request.context_max_total_chunks is not None else CONTEXT_MAX_TOTAL_CHUNKS,
    }
    # 将用户 Query 转换成向量
    query_vector = embedding_service.embed_query(request.query)
    # 执行完整 Retrieval：Vector + BM25 + RRF + Parent 去重 + Reranker
    results = retriever.search(
        query=request.query,
        vector=query_vector,
        child_top_k=request.child_top_k,
        parent_top_k=request.parent_top_k,
        document_id=request.document_id,
        evaluation=True,
        rrf_k=effective_parameters["rrf_k"],
        reranker_candidates=effective_parameters["reranker_candidates"],
        rerank_min_parent_k=effective_parameters["rerank_min_parent_k"],
        rerank_parent_multiplier=effective_parameters["rerank_parent_multiplier"],
        context_neighbor_window=effective_parameters["context_neighbor_window"],
        context_max_chunks_per_parent=effective_parameters["context_max_chunks_per_parent"],
        context_max_total_chunks=effective_parameters["context_max_total_chunks"],
    )
    # 返回 Retrieval 测试结果
    return {
        "query": request.query,
        "document_id": request.document_id,
        "child_top_k": request.child_top_k,
        "parent_top_k": request.parent_top_k,
        "effective_parameters": effective_parameters,
        "reranker_candidates_requested": results.get("reranker_candidates_requested"),
        "reranker_candidates_actual": results.get("reranker_candidates_actual", len(results.get("rerank_candidates", []))),
        "count": len(results.get("results", [])),
        "results": results
    }
