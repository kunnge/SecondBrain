# rrf

# Vector Results
#       +
# BM25 Results
#       ↓
#      RRF
#       ↓
# Fused Results

"""使用 RRF 融合 Vector Search 和 BM25 Search 的结果"""
class RRFFuser:
    # RRF 常数，用于降低排名对最终得分的影响
    RRF_K = 60
    """Vector + BM25 → RRF"""
    def fuse(self,vector_results,bm25_results,limit: int = 30):
        # 保存每个 Chunk 最终的 RRF 得分
        rrf_scores = {}
        # 保存 Chunk ID 与原始检索结果的对应关系
        results_map = {}
        # 保存 Chunk 在 Vector Search 中的排名
        vector_ranks = {}
        # 保存 Chunk 在 BM25 Search 中的排名
        bm25_ranks = {}
        # 保存 Vector Search 返回的向量距离
        vector_distances = {}
        # 保存 BM25 Search 返回的 BM25 得分
        bm25_scores = {}
        # Vector
        # 遍历 Vector Search 结果，并记录每个 Chunk 的排名
        for rank, item in enumerate(vector_results, start=1):
            # 获取当前 Chunk 的唯一 ID
            row_id = item["id"]
            # 保存当前 Chunk 的原始检索结果
            results_map[row_id] = item
            # 保存当前 Chunk 在 Vector Search 中的排名
            vector_ranks[row_id] = rank
            # 保存当前 Chunk 的向量距离
            vector_distances[row_id] = item.get("vector_distance")
            # 根据 RRF 公式计算 Vector Search 对当前 Chunk 的贡献分数
            rrf_scores[row_id] = (
                rrf_scores.get(row_id, 0.0)
                + 1.0 / (self.RRF_K + rank)
            )
        # BM25
        # 遍历 BM25 Search 结果，并记录每个 Chunk 的排名
        for rank, item in enumerate(bm25_results, start=1):
            # 获取当前 Chunk 的唯一 ID
            row_id = item["id"]
            # 保存当前 Chunk 的原始检索结果
            results_map[row_id] = item
            # 保存当前 Chunk 在 BM25 Search 中的排名
            bm25_ranks[row_id] = rank
            # 保存当前 Chunk 的 BM25 得分
            bm25_scores[row_id] = item.get("bm25_score")
            # 根据 RRF 公式计算 BM25 Search 对当前 Chunk 的贡献分数
            rrf_scores[row_id] = (
                rrf_scores.get(row_id, 0.0)
                + 1.0 / (self.RRF_K + rank)
            )
        # Vector 和 BM25 都没有返回结果时，直接返回空列表
        if not rrf_scores:
            return []
        # RRF 排序
        # 按照 RRF 得分从高到低对所有 Chunk 进行排序
        sorted_ids = sorted(
            rrf_scores,
            key=rrf_scores.get,
            reverse=True
        )
        # 保存最终融合后的结果
        results = []
        # 只获取 RRF 得分最高的前 limit 个 Chunk
        for row_id in sorted_ids[:limit]:
            # 根据 Chunk ID 获取原始检索结果
            item = results_map[row_id]
            # 保存 Chunk 信息以及各检索阶段的排名和得分
            results.append(
                {
                    "id": row_id,
                    "document_id": item.get("document_id"),
                    "parent_id": item.get("parent_id"),
                    "text": item.get("text"),
                    "chunk_metadata": item.get("chunk_metadata"),
                    "chunk_index": item.get("chunk_index"),
                    # 当前 Chunk 在 Vector + BM25 融合后的 RRF 得分
                    "rrf_score": rrf_scores[row_id],
                    # 当前 Chunk 在 Vector Search 中的排名
                    "vector_rank": vector_ranks.get(row_id),
                    # 当前 Chunk 在 BM25 Search 中的排名
                    "bm25_rank": bm25_ranks.get(row_id),
                    # 当前 Chunk 的向量距离
                    "vector_distance": vector_distances.get(row_id),
                    # 当前 Chunk 的 BM25 得分
                    "bm25_score": bm25_scores.get(row_id)
                }
            )
        # 返回 RRF 融合后的 Top-K 结果
        return results