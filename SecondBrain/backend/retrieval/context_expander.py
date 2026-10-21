from sqlalchemy import text
from config.settings import CONTEXT_MAX_CHUNKS_PER_PARENT, CONTEXT_MAX_TOTAL_CHUNKS, CONTEXT_NEIGHBOR_WINDOW


class ContextExpander:
    """Reranker 后的上下文扩展"""
    def __init__( self, engine, neighbor_window: int = CONTEXT_NEIGHBOR_WINDOW, max_chunks_per_parent: int = CONTEXT_MAX_CHUNKS_PER_PARENT, max_total_chunks: int = CONTEXT_MAX_TOTAL_CHUNKS ):
        # 数据库连接
        self.engine = engine
        # 前后扩展的 Chunk 数量
        self.neighbor_window = neighbor_window
        # 每个 Parent 最多保留的 Chunk 数量
        self.max_chunks_per_parent = max_chunks_per_parent
        # 所有 Parent 最多保留的 Chunk 数量
        self.max_total_chunks = max_total_chunks
    """根据 Reranker 命中的 Child 扩展前后上下文"""
    def expand(self, results):
        # 获取 Reranker 命中的代表 Child
        child_ids = [
            result.get("representative_child_id")
            for result in results
            if result.get("representative_child_id")
        ]
        if not child_ids:
            return []

        # 查询命中 Child 所属的 Parent
        parent_sql = text("""  SELECT id, parent_id  FROM document_chunks  WHERE id = ANY(:ids)  """)
        with self.engine.connect() as conn:
            child_rows = conn.execute( parent_sql,{"ids": child_ids}).mappings().all()
        if not child_rows:
            return []
        # 建立 Child → Parent 映射
        child_parent_map = {
            str(row["id"]): row["parent_id"]
            for row in child_rows
        }
        # 获取所有相关 Parent
        parent_ids = list({
            row["parent_id"] for row in child_rows
            if row["parent_id"]
        })
        if not parent_ids:
            return []
        # 一次查询所有相关 Parent 下的 Child
        children_sql = text("""
            SELECT id, document_id, parent_id, text, chunk_metadata
            FROM document_chunks
            WHERE parent_id = ANY(:parent_ids)
            ORDER BY parent_id, (chunk_metadata->>'chunk_index')::int
        """)
        with self.engine.connect() as conn:
            child_rows = conn.execute(children_sql,{"parent_ids": parent_ids}).mappings().all()
        # 按 Parent 分组
        parent_children = {}
        for row in child_rows:
            parent_id = str(row["parent_id"])
            parent_children.setdefault(parent_id, []).append(dict(row))
        # 获取每个命中 Child 的前后上下文
        chunks = []
        for parent_rank, child_id in enumerate(child_ids):
            parent_id = child_parent_map.get(str(child_id))
            if not parent_id:
                continue
            children = parent_children.get(str(parent_id), [])
            # 找到命中的 Child 位置
            target_index = None
            for index, child in enumerate(children):
                if str(child["id"]) == str(child_id):
                    target_index = index
                    break
            if target_index is None:
                continue
            # 计算上下文范围
            start = max(0, target_index - self.neighbor_window)
            end = min(len(children),target_index + self.neighbor_window + 1)
            # 获取当前 Parent 的扩展 Chunk
            parent_chunks = children[start:end]
            # 限制单个 Parent 的 Chunk 数量
            parent_chunks = parent_chunks[:self.max_chunks_per_parent]
            # 添加上下文 Chunk
            for chunk in parent_chunks:
                metadata = chunk.get("chunk_metadata") or {}
                chunk_index = metadata.get("chunk_index")
                # 确保 Chunk Index 为整数
                try:
                    chunk_index = int(chunk_index)
                except (TypeError, ValueError):
                    chunk_index = 0
                chunks.append({
                    "id": chunk["id"],
                    "document_id": chunk["document_id"],
                    "parent_id": chunk["parent_id"],
                    "text": chunk["text"] or "",
                    "chunk_metadata": metadata,
                    "chunk_index": chunk_index,
                    "heading_path": metadata.get("heading_path"),
                    "block_id": metadata.get("block_id"),
                    "block_type": metadata.get("block_type"),
                    # 保存 Reranker 中 Parent 的排名
                    "parent_rank": parent_rank
                })
        # 根据 Chunk ID 去重
        unique_chunks = {}
        for chunk in chunks:
            unique_chunks[str(chunk["id"])] = chunk
        chunks = list(unique_chunks.values())
        # 按 Reranker Parent 排名和 Chunk 顺序排序
        chunks.sort( key=lambda x: ( x.get("parent_rank", 999), x.get("chunk_index", 0) ) )
        # 限制所有 Parent 的总 Chunk 数量
        return chunks[:self.max_total_chunks]
