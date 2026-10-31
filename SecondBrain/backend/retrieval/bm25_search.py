from rank_bm25 import BM25Okapi
from sqlalchemy import text
import jieba


# Query
#  ↓
# jieba
#  ↓
# BM25
#  ↓
# Top-K

"""从数据库读取 Child Chunk，使用「章节路径 + Child 内容」建立 BM25 索引"""
class BM25Search:
    """初始化"""
    def __init__(self, engine):
        self.engine = engine
        # BM25 索引对象，用于后续执行关键词检索
        self.bm25 = None
        # 保存建立 BM25 索引时对应的数据库 Child Chunk 数据
        self.bm25_rows = []
        # 启动时建立 BM25 索引
        self.refresh_bm25_index()
    """重新从数据库加载 Child Chunk 并建立 BM25 索引"""
    def refresh_bm25_index(self):
        # 查询所有 Child Chunk，parent_id 不为空表示当前记录是 Child Chunk
        sql = text(
            """ SELECT id, document_id, parent_id, block_id, text, chunk_metadata, chunk_index FROM document_chunks WHERE parent_id IS NOT NULL AND text IS NOT NULL""")
        # 执行 SQL 查询并获取所有 Child Chunk
        with self.engine.begin() as conn:
            rows = conn.execute(sql).fetchall()
        # 保存数据库中的 Child Chunk，后续 BM25 检索结果需要根据索引位置找到原始数据
        self.bm25_rows = rows
        # 如果数据库中没有 Child Chunk，则不建立 BM25 索引
        if not rows:
            self.bm25 = None
            return
        # 将每个 Child Chunk 转换成「章节路径 + Child 内容」，然后进行中文分词
        corpus = [self._tokenize(self._build_retrieval_text(row)) for row in rows]
        # 使用分词后的所有 Child Chunk 建立 BM25 索引
        self.bm25 = BM25Okapi(corpus)
    """BM25 全局检索"""
    def search(self, query: str, document_id: str | None, limit: int = 50):
        # BM25 索引不存在或者没有索引数据时，直接返回空结果
        if not self.bm25 or not self.bm25_rows:
            return []
        # 将用户查询进行中文分词
        query_tokens = self._tokenize(query)
        # 查询分词后没有有效词语时，无法进行 BM25 检索
        if not query_tokens:
            return []
        # 计算查询语句与 BM25 索引中所有 Child Chunk 的相关性得分
        scores = self.bm25.get_scores(query_tokens)
        candidates = []
        # 遍历所有 Child Chunk 以及对应的 BM25 得分
        for index, score in enumerate(scores):
            # 根据 BM25 返回的索引位置找到对应的数据库记录
            row = self.bm25_rows[index]
            # 如果指定了 document_id，则只保留指定文档中的 Child Chunk
            if (document_id is not None and row.document_id != document_id):
                continue
            # 将 BM25 得分转换为 Python float，方便后续处理
            score = float(score)
            # 没有命中任何词，不参与 BM25 排名
            if score <= 0:
                continue
            # 保存 Child Chunk 在 BM25 索引中的位置以及对应得分
            candidates.append((index, score))
        # 按 BM25 得分从高到低排序
        candidates.sort(key=lambda x: x[1], reverse=True)
        results = []
        # 只获取得分最高的前 limit 个候选结果
        for index, score in candidates[:limit]:
            # 根据索引位置找到原始 Child Chunk
            row = self.bm25_rows[index]
            # 将 Child Chunk 的信息以及 BM25 得分转换成字典返回
            results.append({
                "id": row.id,
                "document_id": row.document_id,
                "parent_id": row.parent_id,
                "block_id": row.block_id,
                "text": row.text,
                "chunk_metadata": row.chunk_metadata,
                "chunk_index": row.chunk_index,
                "bm25_score": score,
            })
        return results
    """中文文本分词。"""
    @staticmethod
    def _tokenize(text_value: str):
        # 输入为空时，不进行分词
        if not text_value:
            return []
        # 使用 jieba 的搜索引擎模式进行中文分词
        tokens = jieba.lcut_for_search(str(text_value))
        # 清理每个词两边的空格，并统一转换成小写
        return [token.strip().lower() for token in tokens if token.strip()]
    """BM25 实际检索文本：章节路径+Child 内容"""
    @staticmethod
    def _build_retrieval_text( row) -> str:
        # 从 Child Chunk 的元数据中获取完整章节路径
        metadata = row.chunk_metadata
        # 从 Child Chunk 的元数据中获取完整章节路径
        heading_path = metadata.get("heading_path")
        # 将章节路径和 Child Chunk 正文拼接，作为 BM25 的实际索引文本
        return (f"章节：{heading_path}\n" f"{row.text}").strip()

