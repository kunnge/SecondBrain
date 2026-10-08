from services.reranker_service import reranker_service


# 重新排序
# Query
# +
# Parent Documents
#       ↓
# Reranker
#       ↓
class Reranker:
    """使用 Reranker 模型对 RRF 候选结果进行重排序"""
    @staticmethod
    def rerank(query: str, results: list[dict], top_k: int ):
        """对 RRF 检索结果进行重排序"""
        # 没有候选结果时直接返回空列表
        if not results:
            return []
        # 保存转换后的候选文档文本
        documents = []
        # 遍历 RRF 返回的候选 Chunk
        for item in results:
            # 获取 Chunk 元数据
            metadata = item.get("chunk_metadata") or {}
            # 获取当前 Chunk 的完整章节路径
            heading_path = metadata.get("heading_path") or ""
            # 将章节路径和 Chunk 内容组合成 Reranker 的输入文本
            documents.append( ( f"章节：{heading_path}\n\n" f"内容：\n{item.get('text') or ''}" ).strip() )
        # 使用 Reranker 模型计算 Query 与候选文档之间的相关性得分
        rerank_results = reranker_service.rerank( query=query, documents=documents, top_k=top_k )
        # 保存重新排序后的结果
        reranked_results = []
        # 遍历 Reranker 返回的排序结果
        for result in rerank_results:
            # 获取原候选结果中的索引
            index = result["index"]
            # 获取 Reranker 计算出的相关性得分
            score = float(result["score"])
            # 根据索引找到原始 Chunk，并复制一份避免直接修改原结果
            item = results[index].copy()
            # 将 Reranker 得分添加到当前 Chunk
            item["rerank_score"] = score
            # 保存重排序后的 Chunk
            reranked_results.append(item)
        # 返回经过 Reranker 重排序后的 Top-K 结果
        return reranked_results