from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Optional

from services.chat_service import chat_service


# 后端对应的实体类
class Message(BaseModel):
    role: str = Field(..., description="角色：user 或 assistant")
    content: str = Field(..., description="消息内容")

class ChatRequest(BaseModel):
    # 用户当前输入的问题
    query: str = Field(..., description="用户当前的问题")
    
    # 指定文档ID，不传则检索全部文档（可选）
    document_id: Optional[str] = Field(None, description="指定文档ID，不传则检索全部文档")
    
    # 历史对话记录（可选）
    history: Optional[List[Message]] = Field( default_factory=list, description="历史对话记录")

    # 最终返回给大模型的 Parent 数量
    top_k: Optional[int] = Field(default=4, ge=1,le=20, description="最终返回的知识片段数量")

# 聊天业务接口
router = APIRouter()

@router.post("/chat")
def chat(request: ChatRequest):
    return chat_service.chat(request)