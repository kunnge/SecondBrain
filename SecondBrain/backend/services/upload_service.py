import json
from pathlib import Path
from typing import List
from fastapi import UploadFile, HTTPException
from langchain_core.documents import Document as LangchainDocument
from sqlalchemy.orm import Session
from db.models import Document, DocumentChunk
from rag.chunk import AdvancedRAGSplitter
from rag.retriever import retriever
from services.embedding_service import embedding_service

# RAG 评测数据目录
EVALUATION_DIR = Path("evaluation/evaluation_chunks")
EVALUATION_DIR.mkdir(parents=True, exist_ok=True)

class UploadService:
    """读取上传的 Markdown 文件"""
    def parse_markdown(self, file: UploadFile) -> List[LangchainDocument]:
        # 检查文件类型
        if not file.filename or not file.filename.endswith(".md"):
            raise HTTPException(status_code=400, detail="请上传 .md 文件")
        try:
            # 直接读取上传文件
            content = file.file.read()
            # UTF-8 解码
            markdown_text = content.decode("utf-8")
            # 创建 LangChain Document
            document = LangchainDocument(
                page_content=markdown_text,
                metadata={"filename": file.filename}
            )
            return [document]
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Markdown 文件必须使用 UTF-8 编码")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Markdown解析失败: {e}")

    """
       获取 Markdown 章节路径
       优先使用 Splitter 生成的 heading_path。
       第一天 > 案例1：从网上搜索图片下载
    """
    @staticmethod
    def get_heading_path(metadata: dict) -> str:
        # 优先使用 heading_path
        heading_path = metadata.get("heading_path")
        if heading_path:
            return heading_path
        # 兼容旧数据
        headers = []
        for key, value in sorted(metadata.items(), key=lambda item: ( int(item[0][1:]) if isinstance(item[0], str) and item[0].startswith("H") and item[0][1:].isdigit() else 999 )):
            if isinstance(key, str) and key.startswith("H") and key[1:].isdigit() and value:
                headers.append(value)
        return " > ".join(headers)

    """获取 H1 / H2 / H3 等标题信息"""
    @staticmethod
    def get_headers(metadata: dict) -> dict:
        return { key: value for key, value in metadata.items() if isinstance(key, str) and key.startswith("H") and key[1:].isdigit() }

    """保存当前上传文档的 RAG 评测数据"""
    def save_evaluation_chunks( self, document: Document, parent_chunks, child_chunks, parent_id_map: dict, filename: str ):
        # 1. Child 按数据库 Parent ID 分组
        children_map = {}
        for child in child_chunks:
            database_parent_id = parent_id_map.get(child.parent_id)
            if database_parent_id is None:
                raise ValueError(f"找不到 Child 对应的数据库 Parent ID: {child.parent_id}")
            children_map.setdefault(database_parent_id, []).append(child)
        # 2. 构造评测数据
        result = {
            "document_id": document.id,
            "filename": filename,
            "parent_count": len(parent_chunks),
            "child_count": len(child_chunks),
            "parents": []
        }
        for parent_index, parent in enumerate(parent_chunks, start=1):
            # Splitter Parent ID
            splitter_parent_id = parent.parent_id
            # 数据库 Parent ID
            database_parent_id = parent_id_map.get(splitter_parent_id)
            if database_parent_id is None:
                raise ValueError(f"找不到数据库 Parent ID: {splitter_parent_id}")
            metadata = parent.metadata or {}
            # Parent
            parent_data = {
                "index": parent_index,
                "parent_id": database_parent_id,
                "document_id": document.id,
                "heading_path": self.get_heading_path(metadata),
                "headers": self.get_headers(metadata),
                "content": parent.text,
                "blocks": [ { "block_type": block_type, "content": block } for block_type, block in parent.blocks ],
                "children": []
            }
            # Child
            parent_children = children_map.get(database_parent_id, [])
            for child_index, child in enumerate(parent_children, start=1):
                parent_data["children"].append({
                    "index": child_index,
                    "child_id": child.child_id,
                    "block_id": child.block_id,
                    "block_type": child.block_type,
                    "chunk_index": child.chunk_index,
                    "content": child.text
                })
            result["parents"].append(parent_data)

        # 3. 根据上传文件名生成 JSON 文件名
        original_filename = Path(filename).name
        output_filename = f"{Path(original_filename).stem}.json"
        output_path = EVALUATION_DIR / output_filename
        # 4. 保存 JSON
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✅ RAG评测数据已生成: {output_path}")
        return output_path

    """
          保存到数据库： Parent + Child + Embedding → PostgreSQL
           export_evaluation:
               False：不生成评测数据
               True：生成评测数据
    """
    def save_document(self,file,documents,parent_chunks,child_chunks,db: Session,export_evaluation: bool = False ):
        try:
            # 获取文件名
            filename = getattr(file, "filename", "untitled.md")
            # 1. 获取完整 Markdown 内容
            raw_content = "\n\n".join(doc.page_content for doc in documents)
            # 2. 创建 Document
            new_doc = Document( filename=filename, raw_content=raw_content )
            db.add(new_doc)
            # 获取 document_id
            db.flush()
            # 3. 保存 Parent Chunk
            parent_orm_chunks = []
            for chunk in parent_chunks:
                parent_orm_chunks.append(DocumentChunk( document_id=new_doc.id, parent_id=None, block_id=None, block_type=None, chunk_index=None, text=chunk.text, chunk_metadata=chunk.metadata ) )
            db.add_all(parent_orm_chunks)
            # 获取数据库 Parent ID
            db.flush()
            # 4. 建立 Parent ID 映射
            parent_id_map = {}
            for chunk, orm in zip(parent_chunks, parent_orm_chunks):
                parent_id_map[chunk.parent_id] = orm.id
            # 5. 保存 Child Chunk
            child_orm_chunks = []
            for chunk in child_chunks:
                database_parent_id = parent_id_map.get(chunk.parent_id)
                if database_parent_id is None:
                    raise ValueError(f"找不到 Parent ID: {chunk.parent_id}")
                child_orm_chunks.append(
                    DocumentChunk(
                        document_id=new_doc.id,
                        parent_id=database_parent_id,
                        block_id=chunk.block_id,
                        block_type=chunk.block_type,
                        chunk_index=chunk.chunk_index,
                        text=chunk.text,
                        chunk_metadata=chunk.metadata,
                        embedding=chunk.embedding
                    )
                )
            db.add_all(child_orm_chunks)
            # 6. 提交数据库
            db.commit()
            # 7. 刷新 BM25 索引
            retriever.refresh_bm25_index()
            # 8. 根据参数生成评测数据
            evaluation_path = None
            if export_evaluation:
                evaluation_path = self.save_evaluation_chunks( document=new_doc, parent_chunks=parent_chunks, child_chunks=child_chunks, parent_id_map=parent_id_map, filename=filename )
            print(f"✅ 文档入库成功: {filename}")
            return new_doc, evaluation_path
        except Exception as e:
            # 回滚数据库事务
            db.rollback()
            print(f"❌ 文档入库失败: {e}")
            raise

    """
           上传 Markdown 文件
           export_evaluation:
               False：正常上传，不生成评测数据
               True：上传后生成评测数据
    """
    def upload_markdown( self,  file, db: Session, export_evaluation: bool = False ):

        # 1. 解析 Markdown
        documents = self.parse_markdown(file)
        # 2. Markdown 切块
        splitter = AdvancedRAGSplitter()
        parent_chunks, child_chunks = splitter.process_documents(documents)
        # 3. 构建 Embedding 文本
        content_texts = []
        for chunk in child_chunks:
            metadata = chunk.metadata or {}
            # 获取章节路径
            heading_path = self.get_heading_path(metadata)
            content_text = ( f"章节路径：\n" f"{heading_path}\n\n" f"正文：\n" f"{chunk.text}" )
            content_texts.append(content_text)
        # 4. 批量生成 Embedding
        content_vectors = embedding_service.embed_documents(content_texts)
        # 5. 绑定向量
        for chunk, content_vector in zip(child_chunks, content_vectors):
            chunk.embedding = content_vector
        # 6. 保存 PostgreSQL
        document, evaluation_path = self.save_document( file=file, documents=documents, parent_chunks=parent_chunks, child_chunks=child_chunks, db=db, export_evaluation=export_evaluation )
        # 7. 返回结果
        return {
            "message": "上传成功",
            "document_id": document.id,
            "parent_chunks": len(parent_chunks),
            "child_chunks": len(child_chunks),
            "evaluation_file": str(evaluation_path) if evaluation_path else None
        }

upload_service = UploadService()