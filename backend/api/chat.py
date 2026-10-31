# asyncio 用于管理异步生成器、取消请求和流式任务
import asyncio
import json
import logging
import uuid
# datetime 用于记录时间，timezone 用于统一使用 UTC 时区
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from config.settings import CHAT_DEFAULT_TOP_K, CHAT_MAX_TOP_K, DEFAULT_USER_ID, MAX_QUERY_LENGTH
from db.database import db_manager
from db.models import Conversation, Message
from services.chat_service import chat_service

# 新建会话请求模型，使用 Pydantic 校验客户端传入的数据
class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)

# 修改会话标题的请求模型，标题不能为空且最多 200 个字符
class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

# 会话归档状态更新模型
class ArchiveUpdate(BaseModel):
    is_archived: bool

# 新建聊天请求模型，包含会话、问题、文档范围和检索数量
class ChatRequest(BaseModel):
    conversation_id: str
    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    document_id: str | None = None
    top_k: int = Field(default=CHAT_DEFAULT_TOP_K, ge=1, le=CHAT_MAX_TOP_K)

# 编辑用户历史提问时使用的请求模型
class EditMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    document_id: str | None = None
    top_k: int = Field(default=CHAT_DEFAULT_TOP_K, ge=1, le=CHAT_MAX_TOP_K)

# 重新生成 AI 回答时使用的请求模型
class RegenerateRequest(BaseModel):
    document_id: str | None = None
    top_k: int = Field(default=CHAT_DEFAULT_TOP_K, ge=1, le=CHAT_MAX_TOP_K)

# 获取当前用户标识，目前从配置中读取默认用户 ID
def current_user_id() -> str:
    return DEFAULT_USER_ID

# 获取带 UTC 时区信息的当前时间，避免不同服务器时区造成时间不一致
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

# 将 ORM 会话对象转换成可返回给前端的字典
def serialize_conversation(conversation: Conversation) -> dict:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "is_archived": conversation.is_archived,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "updated_at": conversation.updated_at.isoformat() if conversation.updated_at else None,
    }

# 将 ORM 消息对象转换成前端需要的消息结构，并允许覆盖状态、来源和内容
def serialize_message( message: Message, *, status: str = "completed", sources: list | None = None, content: str | None = None, ) -> dict:
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "sequence_no": message.sequence_no,
        "role": message.role,
        "content": message.content if content is None else content,
        "sources": sources or [],
        "status": status,
        "error_message": None,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }

# 按会话 ID 和用户 ID 查询会话，避免访问其他用户的会话
def get_conversation(db: Session, conversation_id: str, user_id: str) -> Conversation:
    try:
        parsed_id = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="会话不存在") from exc
    conversation = db.query(Conversation).filter( Conversation.id == parsed_id,  Conversation.user_id == user_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conversation

# 加载指定消息序号之前的对话历史，供模型理解上下文
def load_history(db: Session, conversation_id, before_sequence: int) -> list[dict]:
    rows = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.sequence_no < before_sequence,
        Message.role.in_(["user", "assistant"])
    ).order_by(Message.sequence_no.asc()).all()
    return [{"role": row.role, "content": row.content} for row in rows if row.content]

# 构建聊天 SSE 流式响应，同时将回答逐段发送给前端并保存到数据库
def make_streaming_response( db: Session, conversation: Conversation, user_message: Message, assistant_message: Message, query: str, history: list[dict], top_k: int, document_id: str | None, ) -> StreamingResponse:
    # 将事件数据序列化为 Server-Sent Events 使用的文本格式
    def event(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    # 定义异步事件生成器，负责生成并发送聊天过程中的事件
    async def generate():
        # 暂存每段回答文本，流结束后拼接成完整回答
        answer_parts: list[str] = []
        # 保存检索到的知识来源，最终发送给前端
        sources: list[dict] = []
        # 记录 Agent 返回的异步流，便于结束时关闭资源
        answer_stream = None
        # 标记 AI 回答是否已成功提交到数据库
        assistant_persisted = False
        # 保存原有回答内容，取消或异常时用于恢复
        original_assistant_content = assistant_message.content
        try:
            # 先发送 start 事件，让前端初始化本轮会话和消息状态
            yield event({
                "type": "start",
                "conversation": serialize_conversation(conversation),
                "user_message": serialize_message(user_message),
                "assistant_message": serialize_message(assistant_message, status="streaming", content=""),
            })
            # 调用聊天服务，启动 Agent 的异步回答流
            answer_stream = chat_service.stream_answer( query=query, history=history, top_k=top_k, document_id=document_id, thread_id=str(conversation.id) )
            # 持续读取 Agent 输出的文本片段或知识来源事件
            async for update in answer_stream:
                # delta 表示模型新生成的一段回答文本
                if update["type"] == "delta":
                    delta = update.get("content", "")
                    answer_parts.append(delta)
                    yield event({"type": "delta", "content": delta})
                # sources 表示检索完成后返回的知识来源列表
                elif update["type"] == "sources":
                    sources = update.get("sources", [])
                    yield event({"type": "sources", "sources": sources})

            # 将所有文本片段拼接成完整回答并写入消息对象
            assistant_message.content = "".join(answer_parts)
            # 将 AI 回答对象加入当前数据库会话
            db.add(assistant_message)
            conversation.updated_at = now_utc()
            # 提交当前事务，确保消息内容和会话更新时间持久化
            db.commit()
            # 标记回答已保存，避免 finally 中进行不必要的回滚
            assistant_persisted = True
            yield event({"type": "done", "sources": sources})
        # 处理客户端断开连接或异步任务被取消的情况
        except (GeneratorExit, asyncio.CancelledError):
            # 回滚当前尚未提交的数据库操作
            db.rollback()
            # 重新查询数据库中的 AI 消息，确认是否需要恢复或删除
            stopped_message = db.query(Message).filter(Message.id == assistant_message.id).first()
            if stopped_message is not None:
                # 若之前已有回答内容则恢复，否则删除本次未完成的空消息
                if original_assistant_content:
                    stopped_message.content = original_assistant_content
                else:
                    db.delete(stopped_message)
                db.commit()
            raise
        # 捕获其他异常，记录错误并向前端发送 error 事件
        except Exception as exc:
            # 记录异常堆栈，便于排查 Agent 或检索过程中的故障
            logger.exception("聊天 Agent 流式请求失败")
            # 回滚当前尚未提交的数据库操作
            db.rollback()
            failed_message = db.query(Message).filter(Message.id == assistant_message.id).first()
            if failed_message is not None:
                # 若之前已有回答内容则恢复，否则删除本次未完成的空消息
                if original_assistant_content:
                    failed_message.content = original_assistant_content
                else:
                    db.delete(failed_message)
                db.commit()
            # 限制错误信息长度，避免返回过长的异常详情
            detail = f"{type(exc).__name__}: {str(exc).strip() or '回答生成失败。'}"[:500]
            yield event({"type": "error", "message": detail})
        # 无论成功、取消还是异常，都执行资源清理
        finally:
            if answer_stream is not None:
                # 获取异步生成器的关闭方法，兼容没有 aclose 方法的对象
                close = getattr(answer_stream, "aclose", None)
                if close:
                    await close()
            # 如果回答没有成功保存，则回滚未提交的数据库事务
            if not assistant_persisted:
                db.rollback()

    # 返回 SSE 响应，让前端能够实时接收事件流
    return StreamingResponse(generate(), media_type="text/event-stream", headers={ "Cache-Control": "no-cache", "X-Accel-Buffering": "no" })

# 查询并锁定会话行，降低同一会话并发写入导致的顺序冲突
def lock_conversation(db: Session, conversation_id: str, user_id: str) -> Conversation:
    conversation = get_conversation(db, conversation_id, user_id)
    return db.query(Conversation).filter(Conversation.id == conversation.id).with_for_update().one()

# 查询当前会话最大的消息序号并返回下一个可用序号
def next_sequence(db: Session, conversation_id) -> int:
    maximum = db.query(func.max(Message.sequence_no)).filter(
        Message.conversation_id == conversation_id,
    ).scalar() or 0
    return maximum + 1



# 创建 FastAPI 路由对象，供主应用注册聊天相关接口
router = APIRouter(prefix="/conversations")
# 使用当前模块名称创建日志记录器，便于定位接口运行错误
logger = logging.getLogger(__name__)

# 查询当前用户的会话列表，可通过 include_archived 控制是否包含归档会话
@router.get("")
def list_conversations( include_archived: bool = Query(default=False), db: Session = Depends(db_manager.get_db), user_id: str = Depends(current_user_id) ):
    query = db.query(Conversation).filter(Conversation.user_id == user_id)
    if not include_archived:
        query = query.filter(Conversation.is_archived.is_(False))
    conversations = query.order_by(Conversation.updated_at.desc(), Conversation.id.asc()).all()
    return [serialize_conversation(item) for item in conversations]

# 创建一个新会话
@router.post("")
def create_conversation( request: ConversationCreate, db: Session = Depends(db_manager.get_db), user_id: str = Depends(current_user_id) ):
    title = (request.title or "新对话").strip() or "新对话"
    conversation = Conversation(user_id=user_id, title=title)
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return serialize_conversation(conversation)

# 获取指定会话的基本信息
@router.get("/{conversation_id}")
def get_conversation_detail(  conversation_id: str, db: Session = Depends(db_manager.get_db), user_id: str = Depends(current_user_id) ):
    return serialize_conversation(get_conversation(db, conversation_id, user_id))

# 获取指定会话的全部消息，并按消息序号排序
@router.get("/{conversation_id}/messages")
def get_messages( conversation_id: str, db: Session = Depends(db_manager.get_db), user_id: str = Depends(current_user_id) ):
    conversation = get_conversation(db, conversation_id, user_id)
    messages = db.query(Message).filter( Message.conversation_id == conversation.id).order_by(Message.sequence_no.asc()).all()
    return [serialize_message(item) for item in messages]

# 修改指定会话的标题
@router.patch("/{conversation_id}")
def rename_conversation( conversation_id: str, request: ConversationUpdate, db: Session = Depends(db_manager.get_db), user_id: str = Depends(current_user_id) ):
    conversation = get_conversation(db, conversation_id, user_id)
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="会话标题不能为空")
    conversation.title = title
    conversation.updated_at = now_utc()
    db.commit()
    db.refresh(conversation)
    return serialize_conversation(conversation)

# 更新会话的归档状态
@router.patch("/{conversation_id}/archive")
def archive_conversation(  conversation_id: str, request: ArchiveUpdate, db: Session = Depends(db_manager.get_db),  user_id: str = Depends(current_user_id)):
    conversation = get_conversation(db, conversation_id, user_id)
    conversation.is_archived = request.is_archived
    conversation.updated_at = now_utc()
    db.commit()
    db.refresh(conversation)
    return serialize_conversation(conversation)

# 删除指定会话及其关联数据，具体级联行为取决于 ORM 模型配置
@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str,db: Session = Depends(db_manager.get_db),user_id: str = Depends(current_user_id)):
    conversation = get_conversation(db, conversation_id, user_id)
    db.delete(conversation)
    db.commit()
    return {"deleted": True}

# 提交新的聊天问题，并以 SSE 形式返回 AI 的流式回答
@router.post("/chat")
def chat(request: ChatRequest,db: Session = Depends(db_manager.get_db),user_id: str = Depends(current_user_id)):
    # 去除问题首尾空白，避免空格被当成有效问题
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=422, detail="问题内容不能为空")
    # 校验会话归属并加行锁，保证本次会话写入的安全性
    conversation = lock_conversation(db, request.conversation_id, user_id)
    # 获取当前最后一条消息的序号
    last_sequence = next_sequence(db, conversation.id) - 1
    # 加载本轮提问之前的历史消息作为模型上下文
    history = load_history(db, conversation.id, last_sequence + 1)
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=query,
        sequence_no=last_sequence + 1,
    )
    # 创建用于保存重新生成回答的 AI 消息记录
    assistant_message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="assistant",
        content="",
        sequence_no=last_sequence + 2,
    )
    # 将用户提问和待生成的 AI 消息一起加入数据库会话
    db.add_all([user_message, assistant_message])
    # 如果这是会话中的第一条提问，则使用问题内容自动生成标题
    if last_sequence == 0 and conversation.title == "新对话":
        conversation.title = query[:30] + ("…" if len(query) > 30 else "")
    conversation.updated_at = now_utc()
    db.commit()
    db.refresh(user_message)
    db.refresh(assistant_message)
    db.refresh(conversation)
    # 将已创建的消息和历史上下文交给流式响应生成器
    return make_streaming_response(
        db, conversation, user_message, assistant_message, query, history,
        request.top_k, request.document_id,
    )

# 编辑历史用户提问，并重新生成该提问对应的回答
@router.post("/{conversation_id}/messages/{message_id}/edit")
def edit_user_message(conversation_id: str,message_id: str,request: EditMessageRequest,db: Session = Depends(db_manager.get_db),user_id: str = Depends(current_user_id)):
    conversation = lock_conversation(db, conversation_id, user_id)
    # 查询待编辑消息，并限定它必须属于当前会话
    message = db.query(Message).filter(Message.id == message_id, Message.conversation_id == conversation.id).first()
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    # 仅允许编辑用户提问，不允许直接编辑 AI 回答
    if message.role != "user":
        raise HTTPException(status_code=400, detail="只能编辑用户提问")
    query = request.content.strip()
    if not query:
        raise HTTPException(status_code=422, detail="问题内容不能为空")
    # 只加载被编辑消息之前的历史，避免把旧问题及之后内容带入上下文
    history = load_history(db, conversation.id, message.sequence_no)
    # 删除被编辑消息之后的旧消息，确保新回答不会与旧对话混杂
    db.query(Message).filter(Message.conversation_id == conversation.id, Message.sequence_no > message.sequence_no).delete(synchronize_session=False)
    message.content = query
    # 创建用于保存重新生成回答的 AI 消息记录
    assistant_message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="assistant",
        content="",
        sequence_no=message.sequence_no + 1,
    )
    if message.sequence_no == 1 and conversation.title == "新对话":
        conversation.title = query[:30] + ("…" if len(query) > 30 else "")
    conversation.updated_at = now_utc()
    db.commit()
    # 将已创建的消息和历史上下文交给流式响应生成器
    return make_streaming_response(
        db, conversation, message, assistant_message, query, history,
        request.top_k, request.document_id,
    )

# 重新生成指定 AI 消息的回答内容
@router.post("/{conversation_id}/messages/{message_id}/regenerate")
def regenerate_answer(conversation_id: str,message_id: str,request: RegenerateRequest,db: Session = Depends(db_manager.get_db),user_id: str = Depends(current_user_id)):
    conversation = lock_conversation(db, conversation_id, user_id)
    # 查询需要重新生成的 AI 消息并校验其所属会话
    assistant_message = db.query(Message).filter(Message.id == message_id,Message.conversation_id == conversation.id).first()
    if assistant_message is None or assistant_message.role != "assistant":
        raise HTTPException(status_code=400, detail="只能重新生成 AI 回答")
    # 查找该 AI 回答之前最近的一条用户提问
    user_message = db.query(Message).filter(Message.conversation_id == conversation.id,Message.role == "user", Message.sequence_no < assistant_message.sequence_no).order_by(Message.sequence_no.desc()).first()
    if user_message is None:
        raise HTTPException(status_code=400, detail="找不到对应的问题")
    # 加载原始提问之前的历史作为重新生成时的上下文
    history = load_history(db, conversation.id, user_message.sequence_no)
    # 删除被编辑消息之后的旧消息，确保新回答不会与旧对话混杂
    db.query(Message).filter(Message.conversation_id == conversation.id, Message.sequence_no > assistant_message.sequence_no).delete(synchronize_session=False)
    conversation.updated_at = now_utc()
    db.commit()
    # 清空旧回答内容，准备写入新生成的回答
    assistant_message.content = ""
    # 将已创建的消息和历史上下文交给流式响应生成器
    return make_streaming_response(
        db, conversation, user_message, assistant_message, user_message.content,
        history, request.top_k, request.document_id,
    )