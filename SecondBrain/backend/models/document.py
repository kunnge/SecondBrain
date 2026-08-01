# Document 数据模型



import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector

from backend.database.database import Base



# ==========================================
# 1. 文档主表模型
# ==========================================
class Document(Base):
    __tablename__ = 'documents'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(255), nullable=False)

    # 保存完整的 Markdown 纯文本内容
    raw_content = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # 一对多关联：与 DocumentChunk 绑定
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


# ==========================================
# 2. 文档切片 (Chunk) 模型 - 支持父子块逻辑
# ==========================================
class DocumentChunk(Base):
    __tablename__ = 'document_chunks'

    # 基础信息
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 关联到 Document 表
    document_id = Column(String(36), ForeignKey('documents.id'), nullable=False)

    # 自关联外键：用于实现 Parent-Child (父子块) 逻辑
    parent_id = Column(String(36), ForeignKey('document_chunks.id'), nullable=True)

    # 文本内容与节点类型
    text = Column(Text, nullable=False)
    node_type = Column(String(50))

    # 元数据 (如层级、标题等)
    chunk_metadata = Column(JSONB)

    # 向量字段：父块允许为空，子块存入 embedding
    embedding = Column(Vector(512), nullable=True)

    # 反向关联回 Document
    document = relationship("Document", back_populates="chunks")

    # 父子自关联关系：方便通过 chunk.children 获取该父块下的所有子块
    children = relationship("DocumentChunk", backref="parent", remote_side=[id])