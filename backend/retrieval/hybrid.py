from sqlalchemy import text

from retrieval.context_expander import ContextExpander
from config.settings import CONTEXT_MAX_CHUNKS_PER_PARENT, CONTEXT_MAX_TOTAL_CHUNKS, CONTEXT_NEIGHBOR_WINDOW, RERANK_MIN_PARENT_K, RERANK_PARENT_MULTIPLIER, RETRIEVAL_CHILD_TOP_K, RETRIEVAL_PARENT_TOP_K


#            Query
#                   │
# ┌───────────┴───────────┐
# ↓                       ↓
# VectorSearch           BM25Search
# Top - 30                Top - 30
# │                       │
# └───────────┬───────────┘
#              ↓
        # RRFFuser
        # ↓
        # Child结果
        # ↓
        # Parent去重
        # ↓
        # 查询
        # Parent
        # 内容
        # ↓
        # Reranker
        # ↓
        # Parent
        # Top - K

"""混合检索：Vector + BM25 + RRF + Parent 去重 + Reranker"""
class HybridRetriever:
    # Reranker 最少保留的 Parent 候选数量
    MIN_RERANK_PARENT_K = RERANK_MIN_PARENT_K
    def __init__( self, engine, vector_search, bm25_search, rrf_fuser, reranker ):
        # 保存数据库连接引擎
        self.engine = engine
        # 使用外部创建好的向量检索器
        self.vector_search = vector_search
        # 使用外部创建好的 BM25 检索器
        self.bm25_search = bm25_search
        # 使用外部创建好的 RRF 融合器
        self.rrf_fuser = rrf_fuser
        # 使用外部创建好的 Reranker
        self.reranker = reranker
        # 上下文扩展器
        self.context_expander = ContextExpander(engine=engine, neighbor_window=CONTEXT_NEIGHBOR_WINDOW, max_chunks_per_parent=CONTEXT_MAX_CHUNKS_PER_PARENT, max_total_chunks=CONTEXT_MAX_TOTAL_CHUNKS)
    """执行完整混合检索流程"""
    def search(
        self,
        query: str,
        vector: list[float],
        child_top_k: int = RETRIEVAL_CHILD_TOP_K,
        parent_top_k: int = RETRIEVAL_PARENT_TOP_K,
        document_id: str | None = None,
        evaluation: bool = False,
        rrf_k: int | None = None,
        reranker_candidates: int | None = None,
        rerank_min_parent_k: int | None = None,
        rerank_parent_multiplier: int | None = None,
        context_neighbor_window: int | None = None,
        context_max_chunks_per_parent: int | None = None,
        context_max_total_chunks: int | None = None,
    ):
        effective_rrf_k = self.rrf_fuser.RRF_K if rrf_k is None else rrf_k
        effective_rerank_min_parent_k = self.MIN_RERANK_PARENT_K if rerank_min_parent_k is None else rerank_min_parent_k
        effective_rerank_parent_multiplier = RERANK_PARENT_MULTIPLIER if rerank_parent_multiplier is None else rerank_parent_multiplier
        effective_context_neighbor_window = self.context_expander.neighbor_window if context_neighbor_window is None else context_neighbor_window
        effective_context_max_chunks_per_parent = self.context_expander.max_chunks_per_parent if context_max_chunks_per_parent is None else context_max_chunks_per_parent
        effective_context_max_total_chunks = self.context_expander.max_total_chunks if context_max_total_chunks is None else context_max_total_chunks
        configured_reranker_candidates = max(
            parent_top_k * effective_rerank_parent_multiplier,
            effective_rerank_min_parent_k,
        )
        requested_reranker_candidates = (
            configured_reranker_candidates if reranker_candidates is None else reranker_candidates
        )
        if reranker_candidates is not None and not parent_top_k <= reranker_candidates <= child_top_k:
            raise ValueError("reranker_candidates must be between parent_top_k and child_top_k")
        # 1. 设置候选数量
        candidate_k = child_top_k
        # 2. Vector Search：根据向量相似度召回 Child
        vector_results = self.vector_search.search( vector=vector, document_id=document_id, limit=candidate_k )
        # 3. BM25 Search：根据关键词匹配召回 Child
        bm25_results = self.bm25_search.search( query=query, document_id=document_id, limit=candidate_k )
        # 4. Vector + BM25 → RRF：融合两路检索结果
        fused_children = self.rrf_fuser.fuse(
            vector_results=vector_results,
            bm25_results=bm25_results,
            limit=candidate_k,
            rrf_k=effective_rrf_k,
        )
        # 两路检索都没有得到有效结果时直接返回
        if not fused_children:
            if evaluation: return {"vector_results": vector_results, "bm25_results": bm25_results, "rrf_results": [],"rerank_candidates": [],"reranker_candidates_requested": requested_reranker_candidates,"reranker_candidates_actual": 0,"results": []}
            return []
        # 5. Child → Parent 去重：每个 Parent 只保留 RRF 得分最高的 Child
        parent_best = {}
        # 遍历 RRF 融合后的 Child 候选
        for item in fused_children:
            # 获取当前 Child 所属的 Parent ID
            parent_id = item.get("parent_id")
            # 没有关联 Parent 时跳过
            if not parent_id:
                continue
            # 当前 Parent 第一次出现，或者当前 Child 的 RRF 得分更高时更新
            if ( parent_id not in parent_best or item["rrf_score"] > parent_best[parent_id]["rrf_score"] ):
                parent_best[parent_id] = item
        # 没有有效 Parent 时直接返回
        if not parent_best:
            if evaluation: return {"vector_results": vector_results, "bm25_results": bm25_results,"rrf_results": fused_children, "rerank_candidates": [],"reranker_candidates_requested": requested_reranker_candidates,"reranker_candidates_actual": 0,"results": []}
            return []
        # 6. 按 RRF 分数排序：获取 Parent 的初步排序
        sorted_parents = sorted( parent_best.items(), key=lambda item: item[1]["rrf_score"], reverse=True )
        # RRF is capped at child_top_k, so reranking can only use available unique parents.
        rerank_parent_k = min(requested_reranker_candidates, len(sorted_parents))
        # 截取前面的 Parent 作为 Reranker 候选
        sorted_parents = sorted_parents[:rerank_parent_k]
        # 8. 查询 Parent 完整内容
        # 提取所有待查询的 Parent ID
        parent_ids = [ parent_id for parent_id, _ in sorted_parents ]
        # 根据 Parent ID 批量查询 Parent 内容
        parent_sql = text(
            """ SELECT id, document_id, text, chunk_metadata FROM document_chunks WHERE id = ANY(:ids) """ )
        # 执行 Parent 查询
        with self.engine.begin() as conn:
            parent_rows = conn.execute( parent_sql, {"ids": parent_ids} ).fetchall()
        # 将查询结果转换成 Parent ID → Parent 数据的映射
        parent_map = { row.id: row for row in parent_rows }
        # 9. 构造 Reranker 输入
        rerank_results = []
        # 遍历经过 RRF 排序后的 Parent 候选
        for parent_id, item in sorted_parents:
            # 根据 Parent ID 获取完整 Parent 数据
            row = parent_map.get(parent_id)
            # 数据库中没有找到对应 Parent 时跳过
            if not row:
                continue
            # 获取 Parent 元数据
            parent_metadata = row.chunk_metadata or {}
            # 构造 Reranker 所需要的 Parent 数据
            result = {
                # Parent ID
                "id": row.id,
                # 文档 ID
                "document_id": row.document_id,
                # Parent ID
                "parent_id": row.id,
                # Parent 完整文本
                "text": row.text or "",
                # Parent 元数据
                "chunk_metadata": parent_metadata,
                # 代表 Child ID
                "representative_child_id": item.get("id"),
                "representative_block_id": item.get("block_id"),
                # 代表 Child 索引
                "representative_chunk_index": item.get("chunk_index"),
                # Vector 距离
                "vector_distance": item.get("vector_distance"),
                # Vector 排名
                "vector_rank": item.get("vector_rank"),
                # BM25 得分
                "bm25_score": item.get("bm25_score"),
                # BM25 排名
                "bm25_rank": item.get("bm25_rank"),
                # RRF 得分
                "rrf_score": item.get("rrf_score"),
                # 当前阶段的原始检索得分使用 RRF 得分
                "retrieval_score": item.get("rrf_score"),
                # Reranker 尚未执行，初始得分为 0
                "rerank_score": 0.0
            }
            # 将当前 Parent 添加到 Reranker 候选列表
            rerank_results.append(result)
        # 没有有效 Reranker 候选时直接返回
        if not rerank_results:
            if evaluation:
                return {"vector_results": vector_results, "bm25_results": bm25_results,"rrf_results": fused_children, "rerank_candidates": [], "reranker_candidates_requested": requested_reranker_candidates,"reranker_candidates_actual": 0, "results": []}
            return []
        # 10. Reranker：对 Parent 候选重新排序并返回最终 Top-K
        final_results = self.reranker.rerank( query=query, results=rerank_results, top_k=parent_top_k )
        # 11. 上下文扩展
        context_chunks = self.context_expander.expand(
            final_results,
            neighbor_window=effective_context_neighbor_window,
            max_chunks_per_parent=effective_context_max_chunks_per_parent,
            max_total_chunks=effective_context_max_total_chunks)
        # 测试模式返回所有阶段结果
        if evaluation:
            return {
                "vector_results": vector_results,
                "bm25_results": bm25_results,
                "rrf_results": fused_children,
                "rerank_candidates": rerank_results,
                "reranker_candidates_requested": requested_reranker_candidates,
                "reranker_candidates_actual": len(rerank_results),
                "context_chunks": context_chunks,
                "results": final_results,
            }
        # 正常模式只返回最终结果
        return { "results": final_results, "context_chunks": context_chunks }
