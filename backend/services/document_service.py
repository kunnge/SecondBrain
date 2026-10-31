import math
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from config.settings import DOCUMENT_PAGE_SIZE
from db.models import Document



class DocumentService:
    # 将文档模型转换为前端需要的字典格式
    @staticmethod
    def serialize_document(document: Document, include_content: bool = False) -> dict:
        raw_content = document.raw_content or ""
        result = {
            "id": document.id,
            "filename": document.filename,
            "title": document.title or Path(document.filename).stem,
            "summary": document.summary or "",
            "category": document.category or "未分类",
            "tags": document.tags or [],
            "keywords": document.keywords or [],
            "size": len(raw_content.encode("utf-8")),  # 计算文档内容的 UTF-8 字节数。
            "processing_status": getattr(document, "processing_status", "completed") or "completed",
            "metadata_status": document.metadata_status or "pending",
            "metadata_error": document.metadata_error,
            "created_at": document.created_at.isoformat() if document.created_at else datetime.utcnow().isoformat(),
            "updated_at": document.updated_at.isoformat() if getattr(document, "updated_at", None) else None,
        }
        if include_content:
            result["content"] = raw_content  # 按需返回完整文档内容。
        return result

    """分页查询文档，并返回分类、标签等筛选选项"""
    def list_documents(self, db: Session, q: str | None = None, category: str | None = None,tag: str | None = None, page: int = 1, page_size: int = DOCUMENT_PAGE_SIZE) -> dict:
        query = db.query(Document)
        keyword = (q or "").strip()
        # 在标题、文件名、摘要、正文、标签和关键词中模糊搜索。
        if keyword:
            pattern = f"%{keyword}%"
            query = query.filter(or_(
                Document.title.ilike(pattern), Document.filename.ilike(pattern),
                Document.summary.ilike(pattern), Document.raw_content.ilike(pattern),
                cast(Document.tags, String).ilike(pattern), cast(Document.keywords, String).ilike(pattern),
            ))
        # 筛选指定分类，兼容空分类和“未分类”。
        if category:
            if category == "未分类":
                query = query.filter(or_(Document.category.is_(None), Document.category == "", Document.category == "未分类"))
            else:
                query = query.filter(Document.category == category)
        # 筛选包含指定标签的文档。
        if tag:
            query = query.filter(Document.tags.contains([tag]))
        # 统计总数、计算总页数，并修正超出范围的页码。
        total = query.count()
        total_pages = max(1, math.ceil(total / page_size))
        page = min(page, total_pages)
        # 按创建时间倒序、文档 ID 升序查询当前页数据。
        rows = (query.order_by(Document.created_at.desc(), Document.id.asc()).offset((page - 1) * page_size).limit(page_size).all())
        # 获取数据库中已有的分类，排除空值和重复分类。
        category_rows = db.query(Document.category).distinct().all()
        categories = sorted({row[0] for row in category_rows if row[0] and row[0] != "未分类"},key=str.casefold )

        # 检查是否存在空分类或显式标记为“未分类”的文档。
        has_uncategorized = db.query(Document.id).filter(or_(Document.category.is_(None), Document.category == "")).first()
        if has_uncategorized or any(row[0] == "未分类" for row in category_rows):
            categories.append("未分类")

        # 提取所有标签，去除空值并按忽略大小写的顺序排序。
        tag_rows = db.query(Document.tags).all()
        tags = sorted( { str(value).strip() for row in tag_rows for value in (row[0] or []) if str(value).strip() },key=str.casefold)

        # 返回分页结果、总数及可用的分类和标签。
        return {
            "items": [self.serialize_document(document) for document in rows],
            "total": total, "page": page, "page_size": page_size,
            "total_pages": total_pages, "categories": categories, "tags": tags,
        }

    """根据文档 ID 查询详情，不存在时返回 404"""
    def get_document(self, db: Session, document_id: str, include_content: bool = True) -> dict:
        document = db.query(Document).filter(Document.id == document_id).first()
        if document is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        return self.serialize_document(document, include_content=include_content)

    """ 更新文档元数据，并在成功后返回最新文档信息"""
    def update_document(self, db: Session, document_id: str, changes: dict) -> dict:
        document = db.query(Document).filter(Document.id == document_id).first()
        if document is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        if not changes:
            raise HTTPException(status_code=400, detail="没有要保存的修改")

        # 更新标题，去除首尾空格并限制长度为 255 个字符。
        if "title" in changes:
            title = (changes["title"] or "").strip()
            if not title:
                raise HTTPException(status_code=422, detail="标题不能为空")
            document.title = title[:255]

        # 更新摘要和分类，分类为空时使用“未分类”。
        if "summary" in changes and changes["summary"] is not None:
            document.summary = changes["summary"].strip()
        if "category" in changes and changes["category"] is not None:
            document.category = changes["category"].strip() or "未分类"

        # 更新标签和关键词，去除首尾空格并保留原有顺序去重。
        if "tags" in changes and changes["tags"] is not None:
            document.tags = list(dict.fromkeys(value.strip() for value in changes["tags"] if value.strip()))
        if "keywords" in changes and changes["keywords"] is not None:
            document.keywords = list(dict.fromkeys(value.strip() for value in changes["keywords"] if value.strip()))

        # 标记元数据处理完成，清除旧错误信息并保存数据库修改。
        document.metadata_status = "completed"
        document.metadata_error = None
        db.commit()

        # 刷新 ORM 对象，确保返回最新数据。
        db.refresh(document)
        return self.serialize_document(document, include_content=True)

# 创建文档服务实例，供路由层调用。
document_service = DocumentService()
