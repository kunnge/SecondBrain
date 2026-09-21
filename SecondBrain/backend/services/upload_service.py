from fastapi import UploadFile, HTTPException
from langchain_community.document_loaders import TextLoader
from sentence_transformers import SentenceTransformer
from sqlalchemy import create_engine,text,Column,String,Text,DateTime,ForeignKey
from sqlalchemy.orm import relationship, sessionmaker, declarative_base, Session
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
import shutil
import uuid
from pathlib import Path
from typing import List
from datetime import datetime
from backend.rag.chunk import AdvancedRAGSplitter

# 负责连接数据库
class DatabaseManager:
    # 创建 Base 基类
    Base = declarative_base()

    def __init__(self,database_url:str,pool_size:int = 10,max_overflow:int =20):
        """
           初始化数据库连接
        """
        self.database_url = database_url
        # 创建 Engine
        self.engine = create_engine(database_url,pool_pre_ping=True,pool_size=pool_size,max_overflow=max_overflow)
        # 创建 Session 工厂
        self.SessionLocal = sessionmaker(autocommit=False,autoflush=False,bind=self.engine)
    def get_db(self):
        """
            给 FastAPI 接口提供数据库 Session（会话对象),可以操作数据库
        """
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
    def init_db(self):
        """
        初始化数据库
        """
        # 开启 pgvector
        with self.engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
        # 创建所有表
        self.Base.metadata.create_all(bind=self.engine)
        print("数据库初始化完成")

# 连接数据库并初始化
db_manager=DatabaseManager("postgresql+psycopg2://postgres:postgres@localhost:5432/knowledge_base")
db_manager.init_db()

# Embedding 模型服务类
class EmbeddingService:
    def __init__(self):
        # 获取项目根目录
        BASE_DIR = Path(__file__).resolve().parent.parent
        # 本地模型保存路径
        self.model_path = BASE_DIR / "models" / "bge-small-zh-v1.5"
        # 加载模型
        if self.model_path.exists():
            print("加载本地Embedding模型")
            self.embedding_model = SentenceTransformer(str(self.model_path))
        else:
            print("下载Embedding模型")
            self.embedding_model = SentenceTransformer("BAAI/bge-small-zh-v1.5")
            print("模型下载完成")
            # 保存模型到本地
            self.embedding_model.save(str(self.model_path))
    def embed_documents(self,texts:list[str]) -> list[list[float]]:
        """
            文档批量向量化：用于入库
        """
        vectors = self.embedding_model.encode(texts,normalize_embeddings=True)
        return vectors.tolist()
    def embed_query(self,text:str) -> list[float]:
        """
            用户问题向量化：用于检索
        """
        query = ("为这个句子生成表示以用于检索相关文章："+ text)
        vector = self.embedding_model.encode(query,normalize_embeddings=True)
        return vector.tolist()

embedding_service = EmbeddingService()

# 数据模型(数据表)

# 1. 文档主表模型
class Document(DatabaseManager.Base):
    __tablename__ = 'documents'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String(255), nullable=False)

    # 保存完整的 Markdown 纯文本内容
    raw_content = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # 一对多关联：与 DocumentChunk 绑定
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
# 2. 文档切片 (Chunk) 模型 - 支持父子块逻辑
class DocumentChunk(DatabaseManager.Base):
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


# 临时上传目录
UPLOAD_DIR = Path("backend/temp")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# 上传业务
class UploadService:
    def parse_markdown(self, file: UploadFile) -> List[Document]:
        """
        根据上传的 Markdown 文件解析内容

        :param file: 上传md文件
        :return: LangChain Document列表
        """
        # 检查文件类型
        if not file.filename.endswith(".md"):
            raise HTTPException(status_code=400,detail="请上传 .md 文件")
        # 临时文件路径
        file_path = UPLOAD_DIR / file.filename
        try:
            # 保存上传文件
            with open(file_path, "wb") as buffer:shutil.copyfileobj(file.file,buffer)
            # 创建文本加载器
            loader = TextLoader(file_path=str(file_path),encoding="utf-8")
            # 解析markdown
            docs = loader.load()
            # 添加metadata
            for doc in docs:
                doc.metadata["filename"] = file.filename
            return docs
        except Exception as e:
            raise HTTPException(status_code=500,detail=f"Markdown解析失败:{e}")
        finally:
            # 删除临时文件
            if file_path.exists():
                file_path.unlink()
    def upload_markdown(self,file,db: Session):
        """
           上传md文件

           :param file: 上传文件
           :param db: 数据库Session
           """
        # ① 解析 Markdown
        md_text = self.parse_markdown(file)

        # 打印测试
        for index, doc in enumerate(md_text, start=1):
            print(f"===== 文档片段 {index} =====")
            print(doc.page_content)
            print("metadata:")
            print(doc.metadata)
            print("====================")

        # ② 文本切块
        splitter=AdvancedRAGSplitter()
        parent_chunks, child_chunks = splitter.process_documents(md_text)
        # 打印查看结果

        # # 打印父块和子块切分结果
        # print(f"✅ 一共切出了 {len(parent_chunks)} 个父块 + {len(child_chunks)} 个子块")
        #
        # # 打印父块
        # print("\n" + "📦 父块信息".center(80, "="))
        # for i, chunk in enumerate(parent_chunks, start=1):
        #     print(f"\n🏷️  父块 {i}")
        #     print(f"🆔 Parent ID: {chunk.parent_id}")
        #     print(f"📂 Metadata: {chunk.metadata}")
        #     print(f"📄 文本内容:")
        #     print("-" * 80)
        #     print(chunk.text)
        #     print("-" * 80)
        #
        # # 打印子块
        # print("\n" + "🧩 子块信息".center(80, "="))
        # for i, chunk in enumerate(child_chunks, start=1):
        #     print(f"\n🏷️  子块 {i}")
        #     print(f"🆔 Parent ID: {chunk.parent_id}")
        #     print(f"📂 Metadata: {chunk.metadata}")
        #     print(f"📄 文本内容:")
        #     print("-" * 80)
        #     print(chunk.text)
        #     print("-" * 80)
        #
        # print("=" * 80)


        # ③ 生成向量
        # 提取所有子块文本
        texts_to_embed = [chunk.text for chunk in child_chunks]
        # 批量生成向量
        vectors = embedding_service.embed_documents(texts_to_embed)
        # 绑定向量
        for chunk, vector in zip(child_chunks, vectors):
            chunk.embedding = vector  # 给每个子块挂载 embedding 属性
        # 打印测试验证
        # print(f"✅ 成功为 {len(chunks)} 个文本块生成了向量，维度大小: {len(vectors[0])}")


        # ④ 保存数据库 (PostgreSQL + pgvector)
        try:
            # 1. 保存 Document 主表记录
            # 假设你的 file 对象有 filename 属性 (比如 FastAPI 的 UploadFile)
            filename = getattr(file, "filename", "untitled.md")
            # 💡 新增：把刚才解析好的 md_text 里面的内容拼接起来，作为完整原始内容
            raw_content_str = "\n\n".join([doc.page_content for doc in md_text])

            new_doc = Document(filename=filename,raw_content=raw_content_str)
            db.add(new_doc)
            db.flush()  # 刷入数据库，提前生成或确认 new_doc.id，但不提交事务

            # 2. 先插入所有父块，flush 拿到真实数据库 id（父块不存向量，仅保留完整上下文供回溯）
            parent_orm_chunks = []
            for chunk in parent_chunks:
                parent_orm_chunks.append(DocumentChunk(
                    # 关联刚才创建的文档 ID
                    document_id=new_doc.id,
                    # 提取文本与节点类型
                    text=chunk.text,
                    node_type=getattr(chunk, "node_type", "TextNode"),
                    # 映射元数据 (注意你的模型里字段名叫 chunk_metadata)
                    chunk_metadata=getattr(chunk, "metadata", {})
                ))
            db.add_all(parent_orm_chunks)
            db.flush()  # 刷入数据库，拿到父块真实 id，但不提交事务

            # 3. 建立映射：业务父块ID(p_xxx) -> 数据库真实ID(uuid)
            parent_id_map = {}
            for chunk, orm in zip(parent_chunks, parent_orm_chunks):
                parent_id_map[chunk.parent_id] = orm.id

            # 4. 再插入所有子块，parent_id 指向真实存在的 document_chunks.id
            child_orm_chunks = []
            for chunk in child_chunks:
                child_orm_chunks.append(DocumentChunk(
                    # 关联刚才创建的文档 ID
                    document_id=new_doc.id,

                    # 提取文本与节点类型
                    text=chunk.text,
                    node_type=getattr(chunk, "node_type", "TextNode"),

                    # 映射元数据
                    chunk_metadata=getattr(chunk, "metadata", {}),

                    # 映射生成的向量
                    embedding=getattr(chunk, "embedding", None),

                    # 通过映射表换算成真实数据库父块 id，保证外键成立
                    parent_id=parent_id_map[chunk.parent_id]
                ))

            db.add_all(child_orm_chunks)
            # 5. 提交事务
            db.commit()

            # 记录下生成的 Document ID
            document_id = new_doc.id

        except Exception as e:
            # 如果中间任何一步报错（比如向量格式不对、断网等），回滚所有操作，避免产生垃圾数据
            db.rollback()
            print(f"数据库保存失败: {str(e)}")
            raise e

        return {
            "message": "上传成功",
            "chunks": len(parent_chunks) + len(child_chunks)
        }
# 创建的导出对象
upload_service=UploadService()