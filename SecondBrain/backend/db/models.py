import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import relationship
from db.database import Base


# 1. 文档主表模型
class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {"comment": "知识库文档主表"}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="文档唯一标识")
    filename = Column(String(255), nullable=False, comment="上传时的原始文件名")
    raw_content = Column(Text, nullable=True, comment="文档原始内容")
    title = Column(String(255), nullable=True, comment="文档标题")
    summary = Column(Text, nullable=True, comment="文档摘要")
    category = Column(String(100), nullable=True, comment="文档分类")
    tags = Column(JSONB, nullable=False, default=list, comment="文档标签列表")
    keywords = Column(JSONB, nullable=False, default=list, comment="文档关键词列表")
    metadata_status = Column(String(20), nullable=False, default="pending", comment="元数据生成状态")
    processing_status = Column(String(20), nullable=False, default="completed", comment="文档处理状态")
    metadata_error = Column(Text, nullable=True, comment="元数据生成失败原因")
    created_at = Column(DateTime, default=datetime.now(timezone.utc), nullable=False, comment="文档创建时间")
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc), nullable=False, comment="文档最后更新时间")

    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

# 2. 文档切片模型
class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = {"comment": "知识库文档切片表，存储父子切片及向量数据"}

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), comment="切片唯一标识")
    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False, comment="所属文档 ID")
    parent_id = Column(String(36), ForeignKey("document_chunks.id"), nullable=True, comment="父级切片 ID，父块为空，子块指向父块")
    block_id = Column(String(36), nullable=True, comment="原始 Markdown 内容块 ID")
    chunk_index = Column(Integer, nullable=True, comment="切片在内容块中的顺序索引")
    block_type = Column(String(50), nullable=True, comment="内容块类型，如 text、code、list、table")
    text = Column(Text, nullable=False, comment="切片文本内容")
    chunk_metadata = Column(JSONB, comment="切片元数据，如标题路径等上下文信息")
    embedding = Column(Vector(512), nullable=True, comment="切片文本向量，用于语义检索")
    heading_embedding = Column(Vector(512), nullable=True, comment="章节标题向量，用于章节语义检索")

    document = relationship("Document", back_populates="chunks")
    children = relationship("DocumentChunk", back_populates="parent", foreign_keys=[parent_id])
    parent = relationship("DocumentChunk", back_populates="children", remote_side=[id], foreign_keys=[parent_id])

# 3. 聊天会话模型
class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = {"comment": "聊天会话表，存储用户会话及 LangGraph 线程信息"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="会话唯一标识，同时作为 LangGraph thread_id")
    user_id = Column(String(36), nullable=False, index=True, comment="所属用户 ID")
    title = Column(String(200), nullable=True, comment="会话标题")
    is_archived = Column(Boolean, nullable=False, default=False, server_default=text("false"), comment="是否归档")
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False, comment="会话创建时间")
    updated_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc), nullable=False, comment="会话最后活动时间")

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.sequence_no")

# 4. 聊天消息模型
class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence_no", name="uq_messages_conversation_sequence"),
        CheckConstraint("role IN ('user', 'assistant', 'tool')", name="ck_messages_role"),
        Index("ix_messages_conversation_created_at", "conversation_id", "created_at"),
        {"comment": "聊天消息表，存储用户消息、AI 回复及工具消息"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, comment="消息唯一标识")
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, comment="所属会话 ID")
    role = Column(String(20), nullable=False, comment="消息角色：user、assistant 或 tool")
    content = Column(Text, nullable=False, default="", comment="消息正文内容")
    sequence_no = Column(Integer, nullable=False, comment="消息在会话内的顺序编号")
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc), nullable=False, comment="消息创建时间")

    conversation = relationship("Conversation", back_populates="messages")