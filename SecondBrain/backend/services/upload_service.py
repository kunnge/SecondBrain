from backend.database.database import SessionLocal
from backend.models.document import Document, DocumentChunk
from backend.parser.markdown_parser import parse_markdown
from backend.rag.chunk import AdvancedRAGSplitter
from backend.rag.embedding import EmbeddingService

# 上传业务
class UploadService:

    def __init__(self):
        # 实例化刚才写好的 Embedding 专门服务
        self.embedding_service = EmbeddingService()

    def upload_markdown(self,file):
        """
        上传md文件
        :param file:
        :return:
        """
        # ① 解析 Markdown
        md_text = parse_markdown(file)


        # 打印测试
        # for index, doc in enumerate(md_text, start=1):
        #     print(f"===== 文档片段 {index} =====")
        #     print(doc.page_content)
        #     print("metadata:")
        #     print(doc.metadata)
        #     print("====================")


        # ② 文本切块

        splitter=AdvancedRAGSplitter()
        parent_chunks, child_chunks = splitter.process_documents(md_text)

        # 打印查看结果
        print(f"✅ 一共切出了 {len(parent_chunks)} 个父块 + {len(child_chunks)} 个子块\n" + "=" * 50)

        # for i, chunk in enumerate(chunks):
        #     print(f"\n🏷️  [块 {i + 1}] 类型: {chunk.node_type}")
        #     print(f"📂 携带上下文 (Metadata): {chunk.metadata}")
        #     print(f"📄 文本内容:\n{'-' * 40}\n{chunk.text}\n{'-' * 40}")

        # ③ 生成向量（仅子块向量化：子块短、语义集中，用于高精度检索；父块保留完整上下文，供检索后回溯原文）

        # 1. 提取所有子块的文本内容
        texts_to_embed = [chunk.text for chunk in child_chunks]

        # 2. 批量调用生成向量
        vectors = self.embedding_service.get_embeddings(texts_to_embed)

        # 3. 将向量绑定回对应的子块对象
        for chunk, vector in zip(child_chunks, vectors):
            chunk.embedding = vector  # 给每个子块挂载 embedding 属性

        # 打印测试验证
        # print(f"✅ 成功为 {len(chunks)} 个文本块生成了向量，维度大小: {len(vectors[0])}")



        # ④ 保存数据库 (PostgreSQL + pgvector)
        # 获取一个独立的数据库会话
        db = SessionLocal()

        try:
            # 1. 保存 Document 主表记录
            # 假设你的 file 对象有 filename 属性 (比如 FastAPI 的 UploadFile)
            filename = getattr(file, "filename", "untitled.md")

            # 💡 新增：把刚才解析好的 md_text 里面的内容拼接起来，作为完整原始内容
            raw_content_str = "\n\n".join([doc.page_content for doc in md_text])

            new_doc = Document(
                filename=filename,
                raw_content=raw_content_str  # 如果你前面读取了全文，可以存进来
            )
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
            print(f"❌ 数据库保存失败: {str(e)}")
            raise e
        finally:
            # 无论成功失败，都释放数据库连接回连接池
            db.close()


        return {
            "message": "上传成功",
            "chunks": len(parent_chunks) + len(child_chunks)
        }
# 创建的导出对象
upload_service=UploadService()
