import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import relationship
from db.database import Base
# 1. 文档主表模型
class Document(Base):
    __tablename__ = 'documents'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(255), nullable=False)
    raw_content = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # 一对多关联
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
# 2. 文档切片模型
class DocumentChunk(Base):
    __tablename__ = 'document_chunks'
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String(36), ForeignKey('documents.id'), nullable=False)
    # Parent 为 NULL，Child 指向 Parent
    parent_id = Column(String(36), ForeignKey('document_chunks.id'), nullable=True)
    # 原始 Markdown Block ID
    block_id = Column(String(36), nullable=True)
    # Child 在 Block 中的顺序
    chunk_index = Column(Integer, nullable=True)
    # text / code / list / table
    block_type = Column(String(50), nullable=True)
    text = Column(Text, nullable=False)
    chunk_metadata = Column(JSONB)
    # Child 向量
    embedding = Column(Vector(512), nullable=True)
    # 章节标题向量
    heading_embedding = Column(Vector(512), nullable=True)
    # Document 关联
    document = relationship("Document", back_populates="chunks")
    # Parent -> Children
    children = relationship("DocumentChunk",back_populates="parent",foreign_keys=[parent_id])
    # Child -> Parent
    parent = relationship("DocumentChunk",back_populates="children",remote_side=[id],foreign_keys=[parent_id])