import os
from dotenv import load_dotenv
from openai import OpenAI
from rag.retriever import retriever
from services.embedding_service import embedding_service
class ChatService:
    def __init__(self):
        # 先从系统环境变量获取
        api_key = os.getenv("DEEPSEEK_API_KEY")
        # 没有则加载 .env
        if not api_key:
            load_dotenv()
            api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("未找到 DEEPSEEK_API_KEY，系统环境变量和 .env 文件中均未配置！")
        self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    def build_context(self, docs):
        """
        将 Retriever 返回的 Parent + 同章节上下文
        组织成 LLM 可理解的 Context。
        """
        contexts = []
        for index, doc in enumerate(docs, start=1):
            metadata = doc.metadata or {}
            # 章节信息
            headers = []
            for key, value in sorted(metadata.items(), key=lambda x: int(x[0][1:]) if (x[0].startswith("H") and x[0][1:].isdigit()) else 999):
                if key.startswith("H") and value:
                    headers.append(f"{key}: {value}")
            chapter = "\n".join(headers)
            # Parent 完整内容
            content = doc.page_content.strip()
            # 同章节上下文
            context_chunks = metadata.get("context_chunks", [])
            context_parts = []
            for item in context_chunks:
                context_content = (item.get("content") or "").strip()
                if not context_content:
                    continue
                context_parts.append(context_content)
            context_text = ""
            if context_parts:
                context_text = "\n\n【补充上下文】\n" + "\n\n".join(context_parts)
            context = f"""
            【知识片段 {index}】
            
            来源：
            {metadata.get("filename", "未知")}
            
            章节：
            {chapter if chapter else "无章节信息"}
            
            【核心知识】
            {content}
            {context_text}
            """
            contexts.append(context.strip())
        if not contexts:
            return "没有找到相关知识内容。"
        return "\n\n--------------------\n\n".join(contexts)
    def build_prompt(self,query: str,context: str,history: list = None) -> list:
        """为 DeepSeek API 构造 messages。"""
        system_instruction = f"""
        你是一个专业、严谨的知识库问答助手。
        
        请严格基于下方提供的【参考知识】回答用户问题。
        
        【执行规则】
        
        1. 只能使用【参考知识】中的信息回答问题。
        2. 如果参考知识中没有足够的信息，请直接回答：
           “根据当前知识库，我无法回答该问题。”
        3. 不要凭空补充参考知识之外的信息。
        4. 如果参考知识中存在多个相关内容，请综合整理后回答。
        5. 回答较复杂的问题时，请使用 Markdown 分点。
        6. 如果可以确定来源，可以在回答中指出对应的来源或章节。
        7. 【补充上下文】用于帮助理解核心知识的前后关系，
           但同样只能基于其中提供的信息回答。
        8. 历史对话仅用于理解用户当前问题，
           不得将历史回答作为事实依据。
        
        【参考知识】
        
        {context}
        """
        messages = [ { "role": "system", "content": system_instruction } ]
        if history:
            for msg in history:
                role = (msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "user"))
                content = (msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", ""))
                if (role in ["user", "assistant"] and content):
                    messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": query})
        return messages
    def chat(self, request):
        # 1. 用户问题
        query = request.query
        # 2. Query Embedding
        query_vector = embedding_service.embed_query(query)
        # 3. Retriever
        docs = retriever.search(  query=query, vector=query_vector, child_top_k=3 * request.top_k, parent_top_k=request.top_k, document_id=request.document_id )
        # 4. 构造上下文
        context = self.build_context(docs)
        # 5. 构造 Prompt
        prompt = self.build_prompt( query=query, context=context, history=request.history )
        # 6. 调用 DeepSeek
        response = self.client.chat.completions.create( model="deepseek-chat", messages=prompt, temperature=0.1, max_tokens=2048,  stream=False )
        # 7. 获取答案
        answer_text = response.choices[0].message.content
        # 8. 构造 sources
        sources = []
        for doc in docs:
            metadata = doc.metadata
            sources.append({
                # Parent ID
                "id": metadata.get("parent_id"),
                # Parent 完整内容
                "content": doc.page_content,
                # 来源文件
                "filename": metadata.get("filename"),
                # 文档 ID
                "document_id": metadata.get("document_id"),
                # 代表 Child 的向量距离
                "distance": metadata.get("best_child_distance"),
                # 全局 Content RRF
                "global_content_rrf_score": metadata.get("global_content_rrf_score"),
                # 章节内 Content RRF
                "chapter_content_rrf_score": metadata.get("chapter_content_rrf_score"),
                # Chapter / Child 结构关系
                "relation_score": metadata.get("relation_score"),
                # 最终检索分数
                "retrieval_score": metadata.get("retrieval_score"),
                # Reranker 分数
                "rerank_score": metadata.get("rerank_score"),
                # 当前 Parent 所属章节
                "heading_path": metadata.get("heading_path"),
                # 章节检索命中的章节
                "chapter_candidates": metadata.get("chapter_candidates", []),
                # 同章节补充内容
                "context_chunks": metadata.get("context_chunks", [])
            })
        # 9. Retrieval 评测数据
        retrieval_evaluation = []
        for doc in docs:
            metadata = doc.metadata
            retrieval_evaluation.append({
                "parent_id": metadata.get("parent_id"),
                "retrieval_score": metadata.get("retrieval_score"),
                "rerank_score": metadata.get("rerank_score"),
                "best_child_distance": metadata.get("best_child_distance"),
                "global_content_rrf_score": metadata.get("global_content_rrf_score"),
                "chapter_content_rrf_score": metadata.get("chapter_content_rrf_score"),
                "relation_score": metadata.get("relation_score")
            })
        # 10. Parent 评测数据
        parent_evaluation = []
        for doc in docs:
            metadata = doc.metadata
            parent_evaluation.append({
                "parent_id": metadata.get("parent_id"),
                "filename": metadata.get("filename"),
                "document_id": metadata.get("document_id"),
                "content": doc.page_content
            })
        # 11. Heading Path 评测数据
        heading_path_evaluation = []
        for doc in docs:
            metadata = doc.metadata
            heading_path_evaluation.append({
                "parent_id": metadata.get("parent_id"),
                "heading_path": metadata.get("heading_path")
            })
        # 12. Neighbor Chunk 评测数据
        neighbor_evaluation = []
        for doc in docs:
            metadata = doc.metadata
            neighbor_evaluation.append({
                "parent_id": metadata.get("parent_id"),
                "context_chunks": metadata.get("context_chunks", [])
            })
        # 13. 统计信息
        # Parent 数量
        parent_count = len(docs)
        # 唯一 Parent 数量
        unique_parent_ids = {doc.metadata.get("parent_id") for doc in docs if doc.metadata.get("parent_id")}
        unique_parent_count = len(unique_parent_ids)
        # Neighbor Chunk 数量
        neighbor_count = sum(len(doc.metadata.get("context_chunks", [])) for doc in docs)
        # 所有 Chunk ID
        all_chunk_ids = []
        for doc in docs:
            context_chunks = doc.metadata.get("context_chunks", [])
            for chunk in context_chunks:
                if isinstance(chunk, dict):
                    chunk_id = chunk.get("chunk_id")
                    if chunk_id:
                        all_chunk_ids.append(chunk_id)
        # Chunk 去重数量
        unique_chunk_count = len(set(all_chunk_ids))
        # 重复 Chunk 数量
        duplicate_chunk_count = len(all_chunk_ids) - unique_chunk_count
        # Context 长度
        context_length = len(context)
        # 14. RAG Evaluation
        evaluation = {
            # 检索阶段
            "retrieval": retrieval_evaluation,
            # Parent
            "parent": parent_evaluation,
            # Heading Path
            "heading_path": heading_path_evaluation,
            # Neighbor Chunk
            "neighbor": neighbor_evaluation,
            # 最终发送给 LLM 的 Context
            "context": context,
            # 最终答案
            "answer": answer_text,
            # 统计数据
            "stats": {
                "parent_count": parent_count,
                "unique_parent_count": unique_parent_count,
                "neighbor_count": neighbor_count,
                "unique_chunk_count": unique_chunk_count,
                "duplicate_chunk_count": duplicate_chunk_count,
                "context_length": context_length
            }
        }
        # 15. 返回结果
        return {
            "question": query,
            "answer": answer_text,
            "sources": sources,
            "evaluation": evaluation
        }
chat_service = ChatService()