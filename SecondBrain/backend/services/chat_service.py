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

    """将 Parent 和扩展后的 Child 上下文组织成 LLM Context"""
    def build_context(self, docs, context_chunks):
        contexts = []
        # 遍历 Reranker 返回的 Parent
        for index, doc in enumerate(docs, start=1):
            metadata = doc.get("chunk_metadata") or {}
            # 获取章节路径
            chapter = metadata.get("heading_path") or "无章节信息"
            # 获取 Parent 核心内容
            content = (doc.get("text") or "").strip()
            # 获取当前 Parent 对应的上下文 Chunk
            parent_id = doc.get("parent_id")
            related_chunks = [ chunk for chunk in context_chunks if str(chunk.get("parent_id")) == str(parent_id) ]
            context_parts = []
            # 组织上下文 Chunk 内容
            for chunk in related_chunks:
                chunk_content = (chunk.get("text") or "").strip()
                if not chunk_content:
                    continue
                heading_path = chunk.get("heading_path") or ""
                if heading_path:
                    context_parts.append( f"【章节：{heading_path}】\n{chunk_content}" )
                else:
                    context_parts.append(chunk_content)
            # 拼接补充上下文
            context_text = ""
            if context_parts:
                context_text = ( "\n\n【补充上下文】\n" + "\n\n".join(context_parts) )
            # 构建单个知识片段
            context = f"""
                    【知识片段 {index}】
                    来源：
                    {metadata.get("filename", "未知")}
                    章节：
                    {chapter}
                    【核心知识】
                    {content}
                    {context_text}
                    """
            contexts.append(context.strip())
        # 没有检索到内容时返回提示
        if not contexts:
            return "没有找到相关知识内容。"
        # 使用分隔线拼接多个知识片段
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
        retrieval_result = retriever.search(
            query=query,
            vector=query_vector,
            child_top_k=3 * request.top_k,
            parent_top_k=request.top_k,
            document_id=request.document_id
        )
        docs = retrieval_result["results"]
        context_chunks = retrieval_result["context_chunks"]
        # 4. 构造上下文
        context = self.build_context(docs,context_chunks)
        # 5. 构造 Prompt
        prompt = self.build_prompt(
            query=query,
            context=context,
            history=request.history
        )
        # 6. 调用 DeepSeek
        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=prompt,
            temperature=0.1,
            max_tokens=2048,
            stream=False
        )
        # 7. 获取答案
        answer_text = response.choices[0].message.content
        # 8. 只返回答案
        return {
            "answer": answer_text
        }
chat_service = ChatService()