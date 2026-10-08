from sqlalchemy import text

# Query Vector
#     ↓
# PostgreSQL pgvector
#     ↓
# Vector Top-K
class VectorSearch:
    """使用 PostgreSQL pgvector 对 Child Chunk 进行向量检索"""
    def __init__(self, engine):
        # 保存数据库连接引擎
        self.engine = engine
    """全库 Child Vector Search"""
    def search( self, vector: list[float], document_id: str | None = None, limit: int = 50 ):
        # 查询 Child Chunk，并计算查询向量与 Chunk 向量之间的距离
        sql = text(
            """
            SELECT
                id,
                document_id,
                parent_id,
                text,
                chunk_metadata,
                chunk_index,
                embedding <=> CAST(:vector AS vector) AS distance
            FROM document_chunks
            WHERE parent_id IS NOT NULL
              AND embedding IS NOT NULL
              AND (
                  :document_id IS NULL
                  OR document_id = :document_id
              )
            ORDER BY embedding <=> CAST(:vector AS vector)
            LIMIT :limit
            """
        )
        # 执行 SQL，并将查询向量、文档 ID 和返回数量作为参数传入
        with self.engine.begin() as conn:
            rows = conn.execute( sql, { "vector": vector, "document_id": document_id, "limit": limit } ).fetchall()
        # 保存最终的向量检索结果
        results = []
        # 遍历数据库返回的 Child Chunk
        for row in rows:
            results.append(
                {
                    "id": row.id,
                    "document_id": row.document_id,
                    "parent_id": row.parent_id,
                    "text": row.text,
                    "chunk_metadata": row.chunk_metadata,
                    "chunk_index": row.chunk_index,
                    # 将 pgvector 返回的距离转换成 Python float
                    "vector_distance": float(row.distance)
                }
            )
        # 返回按照向量距离从近到远排序后的结果
        return results