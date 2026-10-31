from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config.settings import DOCUMENT_MAX_PAGE_SIZE, DOCUMENT_PAGE_SIZE, MAX_DOCUMENT_QUERY_LENGTH
from db.database import db_manager
from services.document_service import document_service

# 定义文档元数据更新请求模型，用于校验前端提交的更新字段
class DocumentMetadataUpdate(BaseModel):
    title: str | None = None  # 文档标题，允许不传
    summary: str | None = None  # 文档摘要，允许不传
    category: str | None = None  # 文档分类，允许不传
    tags: list[str] | None = None  # 文档标签列表，允许不传
    keywords: list[str] | None = None  # 文档关键词列表，允许不传

# 创建文档管理路由，统一使用 /documents 前缀并标记接口分组
router = APIRouter(prefix="/documents")

# 查询文档列表，支持关键词搜索、分类筛选、标签筛选和分页
@router.get("")
def list_documents(
    q: str | None = Query(default=None, max_length=MAX_DOCUMENT_QUERY_LENGTH),  # 搜索关键词，限制最大长度
    category: str | None = Query(default=None, max_length=100),  # 按文档分类筛选，最多 100 个字符
    tag: str | None = Query(default=None, max_length=100),  # 按文档标签筛选，最多 100 个字符
    page: int = Query(default=1, ge=1),  # 当前页码，最小为 1
    page_size: int = Query(default=DOCUMENT_PAGE_SIZE, ge=1, le=DOCUMENT_MAX_PAGE_SIZE),  # 每页数量，限制在允许范围内
    db: Session = Depends(db_manager.get_db),  # 通过依赖注入获取数据库会话
):
    # 调用文档服务处理筛选和分页，并返回查询结果
    return document_service.list_documents(db, q, category, tag, page, page_size)

# 根据文档 ID 获取文档详情
@router.get("/{document_id}")
def get_document(document_id: str, db: Session = Depends(db_manager.get_db)):
    # 查询指定文档并包含完整正文内容
    return document_service.get_document(db, document_id, include_content=True)

# 根据文档 ID 更新文档元数据
@router.put("/{document_id}")
def update_document(document_id: str,  changes: DocumentMetadataUpdate, db: Session = Depends(db_manager.get_db)):
    # 仅提取请求中实际提供的字段，避免覆盖未提交的元数据
    return document_service.update_document(db, document_id, changes.dict(exclude_unset=True))