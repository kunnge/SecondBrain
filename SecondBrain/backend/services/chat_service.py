# 聊天业务
import os

# question
# -> 生成 query embedding
# -> 调 retriever 检索上下文
# -> 调 generator 生成答案
# -> 返回 answer + sources

from backend.services.upload_service import embedding_service
from dotenv import load_dotenv
from openai import OpenAI
from sqlalchemy import text
from backend.services.upload_service import db_manager
from langchain_core.documents import Document
from sqlalchemy.sql.sqltypes import NULLTYPE


# 向量检索
class VectorRetriever:
    def __init__(self, engine):
        self.engine = engine
    def search( self, vector:list, top_k:int, document_id:str ):
        """
            向量检索
        """
        with self.engine.begin() as conn:
            # 1. 搜索 child chunk
            child_sql = text("""
                SELECT  id, parent_id, text, chunk_metadata, embedding <=> :vector AS distance
                FROM document_chunks
                WHERE  document_id=:document_id AND parent_id IS NOT NULL AND embedding IS NOT NULL
                ORDER BY embedding <=> :vector
                LIMIT :top_k
            """)
            child_rows = conn.execute(
                child_sql, { "vector":vector, "document_id":document_id, "top_k":top_k }
            ).fetchall()
            if not child_rows:
                return []
            # 找父块ID
            parent_ids = list( set( [ row.parent_id for row in child_rows ] ) )
            # 2. 查询 parent chunk
            parent_sql=text("""
                SELECT id, text, node_type, chunk_metadata
                FROM document_chunks
                WHERE id = ANY(:ids)
            """)
            parent_rows = conn.execute( parent_sql, { "ids":parent_ids } ).fetchall()
        # 3. 转 LangChain Document
        docs=[]
        for row in parent_rows:
            docs.append( Document( page_content=row.text, metadata={ "chunk_id":row.id, "node_type":row.node_type, **(row.chunk_metadata or {}) } ) )
        return docs

retriever=VectorRetriever(db_manager.engine)

class ChatService:
    def __init__(self):
        # 1. 先尝试直接从系统环境变量中获取
        api_key = os.getenv("DEEPSEEK_API_KEY")
        # 2. 如果系统环境变量中没有，再去加载 .env 文件
        if not api_key:
            # 寻找并加载当前目录及上级目录的 .env 文件
            load_dotenv()
            # 加载完成后再次尝试获取
            api_key = os.getenv("DEEPSEEK_API_KEY")
        # 3. 如果两边都没有，则抛出明确的错误提示
        if not api_key:
            raise ValueError("未找到 DEEPSEEK_API_KEY，系统环境变量和 .env 文件中均未配置！")
        # 初始化 DeepSeek 客户端 (请替换为你的 API Key)
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"  # DeepSeek 官方 Base URL
        )

    def build_context(self, docs):
        """
        将检索返回的文档块转换为 LLM 可理解的上下文文本
        """
        # 保存所有知识片段
        contexts = []
        # 遍历检索出来的文档
        for index, doc in enumerate(docs, start=1):
            # Document中的metadata
            metadata = doc.metadata or {}

            # 动态生成章节信息
            headers = []
            for key, value in sorted(metadata.items(),key=lambda x: int(x[0][1:]) if x[0].startswith("H") else 999):
                # 找出 H1、H2、H3、H4...
                if key.startswith("H") and value:
                    headers.append( f"{key}: {value}" )

            # 拼接章节
            chapter = "\n".join(headers)

            # 获取文档内容
            content = doc.page_content.strip()
            # 防止单个chunk过长占用过多上下文窗口
            # 一般ParentChunk已经控制大小，这里作为最后保护
            if len(content) > 2000:
                content = content[:2000] + "\n...(内容已截断)"
            # 构造单个知识片段
            context = f"""
    【知识片段 {index}】

    来源:
    {metadata.get("filename", "未知")}

    章节:
   {chapter if chapter else "无章节信息"}

    类型:
    {metadata.get("node_type", "unknown")}

    内容:
    {content}
    """
            # 加入上下文列表
            contexts.append(context.strip())
        # 给LLM一个明确提示
        if not contexts:
            return "没有找到相关知识内容。"
        # 多个知识片段使用分隔符连接
        return "\n\n--------------------\n\n".join(contexts)

    def build_prompt(self,query: str, context: str, history: list = None) -> list:
        """
        为 DeepSeek API 构造标准 messages 列表
        """
        # 1. 构造 System Prompt（系统指令 + 召回的知识）
        # DeepSeek 遵循指令的能力很强，明确给出边界和约束条件
        system_instruction = f"""你是一个专业、严谨的知识库问答助手。
    请**严格基于**下方提供的【参考知识】来回答用户的问题。

    【执行规则】：
    1. 绝对不要凭空捏造，如果【参考知识】中没有明确包含回答问题的信息，请直接回复：“根据当前知识库，我无法回答该问题。”
    2. 不要引入参考知识以外的外部信息。
    3. 如果内容较多，请使用分点列表或适当的 Markdown 格式以保证可读性。
    4. 可以引用参考知识的【来源】或【章节】来增加可信度。

    【参考知识】：
    {context}
    """

        # 初始化消息列表，系统角色打头阵
        messages = [{"role": "system", "content": system_instruction}]

        # 2. 拼接历史对话（如果有）
        # 假设传进来的 history 是 [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
        if history:
            for msg in history:
                # 兼容字典和对象，确保提取出 role 和 content
                role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "user")
                content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
                # 过滤异常数据，确保只传入合法角色
                if role in ["user", "assistant"] and content:
                    messages.append({"role": role, "content": content})

        # 3. 拼接当前用户的提问
        messages.append({"role": "user", "content": query})

        return messages
    def chat(self,request):

        # 1. 用户问题
        query = request.query
        # 2. 问题向量化
        query_vector = embedding_service.embed_query(query)
        # 3. 检索相关知识块
        docs =retriever.search( vector=query_vector, top_k=request.top_k, document_id=request.document_id )
        # 4. 拼接召回原文
        context = self.build_context(docs)
        # 5. 构造Prompt
        prompt = self.build_prompt(
            query=query,
            context=context,
            history=request.history
        )


        # ===============================
        # 6. 调用LLM
        # ===============================

        # 调用 DeepSeek API 生成回答
        response = self.client.chat.completions.create(
            model="deepseek-chat",  # 使用 V3 模型 (或者 deepseek-reasoner 也就是 R1 模型)
            messages=prompt,
            temperature=0.1,  # RAG 场景建议温度调低，0.1~0.3，降低幻觉保证严谨性
            max_tokens=2048,
            stream=True  # 如果需要流式输出打字机效果，这里设为 True
        )

        # 提取真实的文本字符串
        answer_text = response.choices[0].message.content

        # ===============================
        # 7. 返回结果
        # ===============================

        return {
            "question": query,
            "answer": answer_text,
            "sources": [
                {
                    "id": doc.metadata.get("chunk_id"),
                    "content": doc.page_content[:200],
                    "filename": doc.metadata.get("filename"),
                    "node_type": doc.metadata.get("node_type")
                }
                for doc in docs
            ]
        }
chat_service=ChatService()