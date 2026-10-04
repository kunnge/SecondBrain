import jieba
from rank_bm25 import BM25Okapi
from sqlalchemy import text
from langchain_core.documents import Document
from db.database import db_manager
from services.reranker_service import reranker_service


class VectorRetriever:
    # RRF 常数
    RRF_K = 60
    # Reranker 至少保留多少个候选 Parent
    MIN_RERANK_PARENT_K = 12
    def __init__(self, engine):
        self.engine = engine
        # BM25
        self.bm25 = None
        self.bm25_rows = []
        # 启动时建立 BM25 索引
        self.refresh_bm25_index()
    # 主检索流程
    def search( self, query: str, vector: list[float], child_top_k: int = 12, parent_top_k: int = 4, document_id: str | None = None ):
        """
        检索流程：
        Query
          ↓
        Vector Search
          +
        BM25
        （章节标题 + Child 内容）
          ↓
        RRF
          ↓
        Child → Parent 去重
          ↓
        Reranker
        （章节标题 + Parent 内容）
          ↓
        Top-K Parent
        """
        with self.engine.begin() as conn:
            # 1. 候选数量
            candidate_k = max(child_top_k * 3,30)
            # 2. Vector Search
            vector_rows = self._search_content(conn=conn,vector=vector,document_id=document_id,limit=candidate_k)
            # 3. BM25
            bm25_rows = self._search_bm25(query=query,document_id=document_id,limit=candidate_k)
            # 4. Vector + BM25 → RRF
            fused_children = self._rrf_fuse(vector_rows=vector_rows,bm25_rows=bm25_rows,limit=candidate_k)
            if not fused_children:
                return []
            # 5. Child → Parent 去重
            parent_best = {}
            for item in fused_children:
                row = item["row"]
                parent_id = row.parent_id
                if not parent_id:
                    continue
                if ( parent_id not in parent_best or item["rrf_score"] > parent_best[parent_id]["rrf_score"]):
                    parent_best[parent_id] = item
            if not parent_best:
                return []
            # 6. 按 RRF 排序
            sorted_parents = sorted(parent_best.items(),key=lambda x: x[1]["rrf_score"],reverse=True)
            # 给 Reranker 更多候选
            rerank_parent_k = max(parent_top_k * 4,self.MIN_RERANK_PARENT_K)
            sorted_parents = sorted_parents[:rerank_parent_k]
            # 7. 查询 Parent 完整内容
            parent_ids = [parent_id for parent_id, _ in sorted_parents]
            parent_sql = text(""" SELECT id, document_id, text, chunk_metadata FROM document_chunks WHERE id = ANY(:ids)""")
            parent_rows = conn.execute(parent_sql,{"ids": parent_ids}).fetchall()
            parent_map = { row.id: row for row in parent_rows }
            # 8. 构建 Parent Document
            docs = []
            for parent_id, item in sorted_parents:
                row = parent_map.get(parent_id)
                if not row:
                    continue
                representative_child = item["row"]
                heading_path = self._build_heading_path(representative_child.chunk_metadata or {})
                docs.append(Document(page_content=row.text or "",
                        metadata={
                            **( row.chunk_metadata or {} ),
                            "parent_id": row.id,
                            "document_id": ( row.document_id ),
                            "representative_child_id": ( representative_child.id ),
                            "representative_chunk_index": ( representative_child._mapping.get( "chunk_index" ) ),
                            # 章节路径
                            "heading_path": heading_path,
                            # Vector
                            "best_child_distance": ( item["vector_distance"] ),
                            "vector_rank": ( item["vector_rank"] ),
                            # BM25
                            "bm25_score": ( item["bm25_score"] ),
                            "bm25_rank": ( item["bm25_rank"] ),
                            # RRF
                            "rrf_score": ( item["rrf_score"] ),
                            # 兼容原来的 ChatService
                            "retrieval_score": ( item["rrf_score"] ),
                            # Reranker
                            "rerank_score": 0.0
                        }))
            if not docs:
                return []
            # 9. Reranker
            docs = self._rerank( query=query, docs=docs, top_k=parent_top_k )
            return docs
    # Vector Search
    def _search_content( self, conn, vector: list[float], document_id: str | None, limit: int ):
        """全库 Child Vector Search"""
        sql = text(""" SELECT id, document_id, parent_id, text, chunk_metadata, chunk_index, embedding <=> CAST(:vector AS vector) AS distance FROM document_chunks
        WHERE parent_id IS NOT NULL AND embedding IS NOT NULL AND ( :document_id IS NULL OR document_id = :document_id ) ORDER BY embedding <=> CAST(:vector AS vector)
        LIMIT :limit""")
        return conn.execute(sql,{"vector": vector,"document_id": document_id,"limit": limit}).fetchall()
    # BM25
    def refresh_bm25_index(self):
        """从数据库读取所有 Child，使用「章节路径 + Child 内容」建立 BM25 索引。"""
        sql = text(""" SELECT id, document_id, parent_id, text, chunk_metadata, chunk_index FROM document_chunks WHERE parent_id IS NOT NULL AND text IS NOT NULL""")
        with self.engine.begin() as conn:
            rows = conn.execute(sql).fetchall()
        self.bm25_rows = rows
        if not rows:
            self.bm25 = None
            return
        corpus = [ self._tokenize( self._build_retrieval_text(row)) for row in rows ]
        self.bm25 = BM25Okapi(corpus)
    def _build_retrieval_text(self, row) -> str:
        """BM25 实际检索文本：章节路径+Child 内容"""
        heading_path = self._build_heading_path( row.chunk_metadata)
        return ( f"章节：{heading_path}\n" f"{row.text or ''}" ).strip()

    def _search_bm25( self, query: str, document_id: str | None, limit: int ):
        """BM25 全局检索。"""
        if not self.bm25 or not self.bm25_rows:
            return []
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return []
        scores = self.bm25.get_scores(
            query_tokens
        )
        candidates = []
        for index, score in enumerate(scores):
            row = self.bm25_rows[index]
            if ( document_id is not None and row.document_id != document_id ):
                continue
            score = float(score)
            # 没有命中任何词，不参与 BM25 排名
            if score <= 0:
                continue
            candidates.append((index,score))
        candidates.sort(key=lambda x: x[1],reverse=True)
        results = []
        for index, score in candidates[:limit]:
            row = self.bm25_rows[index]
            results.append({"row": row,"bm25_score": score})
        return results
    # 中文分词
    @staticmethod
    def _tokenize(text_value: str):
        """中文文本分词。"""
        if not text_value:
            return []
        tokens = jieba.lcut_for_search( str(text_value) )
        return [ token.strip().lower() for token in tokens if token.strip() ]
    # Heading Path
    @staticmethod
    def _build_heading_path(metadata: dict) -> str:
        """根据 H1/H2/H3...，构造章节路径：第一天 > 案例1 > 第一步"""
        if not metadata:
            return ""
        headings = []
        for key, value in metadata.items():
            if not ( isinstance(key, str) and key.startswith("H") and key[1:].isdigit() ):
                continue
            if not value:
                continue
            headings.append((int(key[1:]),str(value).strip()))
        headings.sort( key=lambda x: x[0])
        return " > ".join( value for _, value in headings )
    # RRF
    def _rrf_fuse(self,vector_rows,bm25_rows,limit: int):
        """Vector + BM25 → RRF"""
        rrf_scores = {}
        rows_map = {}
        vector_ranks = {}
        bm25_ranks = {}
        vector_distances = {}
        bm25_scores = {}
        # Vector
        for rank, row in enumerate(vector_rows, start=1):
            row_id = row.id
            rows_map[row_id] = row
            vector_ranks[row_id] = rank
            vector_distances[row_id] = getattr(row,"distance",None)
            rrf_scores[row_id] = (rrf_scores.get(row_id, 0.0)+ 1.0 / (self.RRF_K + rank))
        # BM25
        for rank, item in enumerate(bm25_rows,start=1):
            row = item["row"]
            row_id = row.id
            rows_map[row_id] = row
            bm25_ranks[row_id] = rank
            bm25_scores[row_id] = (item["bm25_score"])
            rrf_scores[row_id] = (rrf_scores.get(row_id, 0.0)+ 1.0 / (self.RRF_K + rank))
        if not rrf_scores:
            return []
        # RRF 排序
        sorted_ids = sorted(rrf_scores,key=rrf_scores.get,reverse=True)
        results = []
        for row_id in sorted_ids[:limit]:
            results.append({
                "row": rows_map[row_id],
                "rrf_score": (rrf_scores[row_id]),
                "vector_rank": (vector_ranks.get(row_id)),
                "bm25_rank": (bm25_ranks.get(row_id)),
                "vector_distance": (vector_distances.get(row_id)),
                "bm25_score": (bm25_scores.get(row_id))
            })
        return results
    # Reranker
    @staticmethod
    def _rerank(query: str,docs: list[Document],top_k: int):
        """
        Query
          +
        章节路径
          +
        Parent 内容
          ↓
        Reranker
          ↓
        Top-K Parent
        """
        if not docs:
            return []
        documents = []
        for doc in docs:
            heading_path = (doc.metadata.get("heading_path")or "")
            documents.append( ( f"章节：{heading_path}\n\n" f"内容：\n{doc.page_content}" ).strip() )
        results = reranker_service.rerank(query=query,documents=documents,top_k=top_k)
        reranked_docs = []
        for result in results:
            index = result["index"]
            score = result["score"]
            doc = docs[index]
            doc.metadata["rerank_score"] = score
            reranked_docs.append(doc)
        return reranked_docs

retriever = VectorRetriever(db_manager.engine)