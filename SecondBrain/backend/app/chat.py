from backend.services import chat_service
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Optional

# 后端对应的实体类
class Message(BaseModel):
    role: str = Field(..., description="角色：user 或 assistant")
    content: str = Field(..., description="消息内容")

class ChatRequest(BaseModel):
    # 用户当前输入的问题
    query: str = Field(..., description="用户当前的问题")
    
    # RAG 指定为notebook_id知识库（可选）
    notebook_id: Optional[str] = Field(None, description="指定的笔记或知识库ID，如果不填则检索全部")
    
    # 上下文记忆（可选）
    history: Optional[List[Message]] = Field(default=[], description="历史对话记录")
    
    # 控制检索数量
    top_k: Optional[int] = Field(default=4, description="检索相关的知识片段数量")

# 聊天业务接口
router = APIRouter()

@router.post("/chat")
def chat(request: ChatRequest):
    return chat_service.chat(request)