import asyncio
import json
import threading
from typing import Any, TypedDict
from config.settings import AGENT_TOOL_MAX_TOP_K, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE, RETRIEVAL_CHILD_MULTIPLIER
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from rag.retriever import retriever
from services.embedding_service import embedding_service

# LangGraph 节点之间传递的共享状态；total=False 表示字段可以按需省略
class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    top_k: int
    document_id: str | None
# 封装模型调用、知识库检索、工具路由和流式输出的 Agent
"""LangGraph Agent that streams DeepSeek output and reuses the RAG retriever."""
class KnowledgeAgent:
    # 初始化模型客户端、Search 工具定义，并构建 LangGraph 工作流
    def __init__(self):
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise RuntimeError("缺少 openai 依赖") from exc
        # 加载 .env 中的环境变量，供后续读取 API Key 和模型名称
        if not DEEPSEEK_API_KEY:
            raise ValueError("未找到 DEEPSEEK_API_KEY")
        # 使用异步 OpenAI 兼容客户端连接 DeepSeek API
        self.client = AsyncOpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        self.model = DEEPSEEK_MODEL
        # 向模型声明可调用的 Search 工具及其参数结构；这里只是声明，不会立即检索。
        self.search_tool = {
            "type": "function",
            "function": {
                "name": "Search",
                "description": "搜索个人知识库，回答用户问题前优先使用该工具。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "要搜索的问题"},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": AGENT_TOOL_MAX_TOP_K},
                    },
                    "required": ["query"],
                },
            },
        }
        # 创建状态图：模型节点可决定结束回答，也可转到工具节点检索知识
        graph = StateGraph(AgentState)
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", self._tool_node)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self._route_after_agent, {"tools": "tools", "end": END})
        graph.add_edge("tools", "agent")
        self.workflow = graph
        self.graph = graph.compile()
    # 设置 LangGraph 检查点存储，用于持久化/恢复图状态
    def set_checkpointer(self, checkpointer) -> None:
        self.graph = self.workflow.compile(checkpointer=checkpointer)
    # 模型节点：请求 DeepSeek，并将文本增量和工具调用增量分别收集起来
    async def _agent_node(self, state: AgentState, config: RunnableConfig) -> AgentState:
        # 从运行配置中取得流式队列和取消标记，供调用方接收内容或中断任务
        configurable = config.get("configurable", {})
        token_queue: asyncio.Queue = configurable["token_queue"]
        cancel_event: threading.Event = configurable["cancel_event"]
        # 开启流式输出并允许模型自动决定是否调用 Search 工具
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=state["messages"],
            tools=[self.search_tool],
            tool_choice="auto",
            temperature=LLM_TEMPERATURE,
            max_tokens=LLM_MAX_TOKENS,
            stream=True,
            extra_body={"thinking": {"type": "disabled"}},
        )
        # content_parts 保存回答文本片段
        content_parts: list[str] = []
        # tool_calls按调用索引拼接分段工具参数
        tool_calls: dict[int, dict[str, Any]] = {}
        try:
            # 逐块读取模型响应；每个 chunk 可能包含文本或工具调用的一部分。
            async for chunk in response:
                # 用户取消请求时及时停止读取，避免继续消耗模型资源。
                if cancel_event.is_set():
                    raise asyncio.CancelledError()
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta
                # 文本片段立即推送给上层，同时保留一份用于组装完整 assistant 消息。
                if delta.content:
                    content_parts.append(delta.content)
                    token_queue.put_nowait({"type": "delta", "content": delta.content})
                # 工具调用可能被拆成多个流式片段，需要按 index 合并名称和参数。
                for call_delta in delta.tool_calls or []:
                    call = tool_calls.setdefault(
                        call_delta.index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if call_delta.id:
                        call["id"] = call_delta.id
                    function_delta = call_delta.function
                    if function_delta:
                        if function_delta.name:
                            call["function"]["name"] += function_delta.name
                        if function_delta.arguments:
                            call["function"]["arguments"] += function_delta.arguments
        finally:
            # 无论正常结束还是发生异常，都关闭模型响应流。
            await response.close()
        # 将收集到的文本和完整工具调用还原成 LangChain/LangGraph 可用的消息格式。
        assistant: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts)}
        if tool_calls:
            assistant["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
        return {"messages": [*state["messages"], assistant]}
    # 根据模型最后一条消息是否包含 tool_calls，决定继续执行工具还是结束。
    @staticmethod
    def _route_after_agent(state: AgentState) -> str:
        return "tools" if state["messages"][-1].get("tool_calls") else "end"
    # 工具节点：解析模型的工具请求，执行 Search，并把结果作为 tool 消息交还模型。
    async def _tool_node(self, state: AgentState, config: RunnableConfig) -> AgentState:
        configurable = config.get("configurable", {})
        cancel_event: threading.Event = configurable["cancel_event"]
        token_queue: asyncio.Queue = configurable["token_queue"]
        assistant = state["messages"][-1]
        messages = list(state["messages"])
        sources = list(state.get("sources") or [])
        # 逐个处理模型请求的工具调用；当前仅支持名称为 Search 的工具。
        for call in assistant.get("tool_calls", []):
            name = call["function"]["name"]
            arguments = json.loads(call["function"].get("arguments"))
            if name != "Search":
                result = {"error": f"未知工具: {name}"}
            else:
                # 限制召回数量在 1～8 之间，避免模型传入过大或非法的 top_k。
                requested_top_k = arguments.get("top_k", state.get("top_k"))
                safe_top_k = max(1, min(AGENT_TOOL_MAX_TOP_K, int(requested_top_k)))
                result, found_sources = await self.search(  str(arguments.get("query")), safe_top_k, state.get("document_id"),  cancel_event)
                sources.extend(found_sources)
            # 工具结果必须带上 tool_call_id，模型才能将结果与对应调用匹配。
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"],
                "name": name,
                "content": json.dumps(result, ensure_ascii=False),
            })
        # 将本轮检索来源单独推送给前端，便于展示引用/来源列表。
        token_queue.put_nowait({"type": "sources", "sources": sources})
        return {"messages": messages, "sources": sources}
    """执行真正的 RAG 检索：先生成查询向量，再调用已有 retriever 获取相关片段"""
    @staticmethod
    async def search(query: str, top_k: int, document_id: str | None, cancel_event: threading.Event) -> tuple[dict, list[dict]]:
        # 检查任务是否已取消，避免继续执行不必要的检索。
        if cancel_event.is_set():
            raise asyncio.CancelledError()
        # 查询内容为空时，直接返回空检索结果。
        if not query.strip():
            return {"context": "没有找到相关知识内容。", "sources": []}, []
        # 在线程池中执行同步向量计算，避免阻塞异步事件循环。
        vector = await asyncio.to_thread(embedding_service.embed_query, query)
        # 向量计算完成后再次检查取消状态。
        if cancel_event.is_set():
            raise asyncio.CancelledError()
        # 在线程池中执行混合检索，获取相关知识片段。
        result = await asyncio.to_thread(
            retriever.search,
            query=query,
            vector=vector,
            # 扩大子片段候选数量，最终父级文档数量由 parent_top_k 控制
            child_top_k=top_k * RETRIEVAL_CHILD_MULTIPLIER,
            parent_top_k=top_k,
            document_id=document_id,
        )
        # 检索完成后检查取消状态，避免继续处理无用结果。
        if cancel_event.is_set():
            raise asyncio.CancelledError()
        # 从检索结果中提取文档列表，兼容非字典类型的异常返回值。
        docs = result.get("results", []) if isinstance(result, dict) else []
        # 保存返回给前端的来源信息
        sources = []
        # 保存拼接后提供给大模型的知识上下文
        contexts = []
        # 遍历检索结果，提取正文和文档元数据
        for doc in docs:
            metadata = doc.get("chunk_metadata") or {}
            content = (doc.get("text") or "").strip()
            # 整理来源信息，供前端展示引用文档和知识片段。
            sources.append({
                "id": str(doc.get("id") or doc.get("parent_id") or ""),
                "filename": metadata.get("filename") or "未知文档",
                "heading_path": metadata.get("heading_path") or "",
                "node_type": "知识片段",
                "content": content,
            })
            # 将来源文件、章节路径和正文拼接为模型可读取的上下文。
            contexts.append(
                f"来源：{metadata.get('filename', '未知文档')}\n"
                f"章节：{metadata.get('heading_path') or '无章节信息'}\n{content}"
            )
        # 合并所有知识片段，并同时返回检索上下文和来源列表。
        return {
            "context": "\n\n---\n\n".join(contexts) or "没有找到相关知识内容。",
            "sources": sources,
        }, sources

    """定义 Agent 的系统提示词，约束模型的回答和工具调用行为"""
    async def stream( self, query: str, history: list[dict] | None = None, top_k: int = 4, document_id: str | None = None, thread_id: str | None = None):
        system = (
            f"你是个人知识库 Agent，当前模型标识为 {self.model}。"
            "问候、关于你自身身份或模型的问题可以直接简短回答，不要调用 Search。"
            "涉及用户知识、文件内容或事实的问题，必须调用 Search，并且只能根据工具返回的知识回答。"
            "如果 Search 没有相关结果，明确说明当前知识库没有找到相关内容，不要编造。"
        )
        # 过滤历史消息，只保留有效的用户和助手消息。
        safe_history = [
            {"role": item["role"], "content": item["content"]}
            for item in (history or [])
            if item.get("role") in ("user", "assistant") and item.get("content")
        ]
        # 初始化 LangGraph 的状态，传入消息历史、检索数量和文档过滤条件。
        state: AgentState = {
            "messages": [{"role": "system", "content": system}, *safe_history, {"role": "user", "content": query}],
            "sources": [],
            "top_k": top_k,
            "document_id": document_id,
        }
        # 创建异步队列，用于接收 Graph 执行过程中生成的文本片段。
        token_queue: asyncio.Queue = asyncio.Queue()
        # 创建线程安全的取消事件，用于通知底层任务停止生成。
        cancel_event = threading.Event()
        # 异步启动 LangGraph，避免等待整个流程结束后才返回结果。
        graph_task = asyncio.create_task(self.graph.ainvoke(
            state,
            config={
                "recursion_limit": 8,
                "configurable": {
                    "token_queue": token_queue,
                    "cancel_event": cancel_event,
                    "thread_id": thread_id,
                },
            },
        ))
        try:
            # 在 Graph 尚未执行完成时，持续监听文本队列和任务状态。
            while not graph_task.done():
                # 创建一个等待队列数据的任务。
                next_token = asyncio.create_task(token_queue.get())
                # 等待文本到达或 Graph 执行结束，哪个先发生就先处理哪个。
                done, _ = await asyncio.wait({next_token, graph_task},return_when=asyncio.FIRST_COMPLETED)
                # 如果有文本到达，就立即向调用方输出，实现流式响应。
                if next_token in done:
                    yield next_token.result()
                else:
                    # 如果 Graph 已结束，取消尚未完成的队列读取任务。
                    next_token.cancel()
                    await asyncio.gather(next_token, return_exceptions=True)
            # Graph 结束后，输出队列中尚未发送的剩余文本。
            while not token_queue.empty():
                yield token_queue.get_nowait()
            # 获取 Graph 的最终执行结果，并在任务异常时向外传播异常。
            result = await graph_task
            # 检查最终消息是否既没有回答内容，也没有待执行的工具调用。
            if not result["messages"][-1].get("content") and not result["messages"][-1].get("tool_calls"):
                raise RuntimeError("DeepSeek 返回了空回答；请检查模型名称及 API 响应。")
        finally:
            # 通知底层流程停止生成，避免任务结束后仍继续执行。
            cancel_event.set()
            # 如果 Graph 仍在运行，则主动取消任务。
            if not graph_task.done():
                graph_task.cancel()
            # 等待任务彻底结束，并收集取消或执行过程中产生的异常。
            await asyncio.gather(graph_task, return_exceptions=True)

knowledge_agent=KnowledgeAgent()