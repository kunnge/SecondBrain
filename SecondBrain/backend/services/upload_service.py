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
from services.MetadataService import MetadataService

# 定义 RAG 评测数据的保存目录，并在目录不存在时自动创建。
EVALUATION_DIR = Path("evaluation/evaluation_chunks")
EVALUATION_DIR.mkdir(parents=True, exist_ok=True)

class UploadService:

    """读取上传的 Markdown 文件并转换为 LangChain 文档对象"""
    def parse_markdown(self, file: UploadFile) -> List[LangchainDocument]:
        # 检查文件名和扩展名，拒绝非 Markdown 文件。
        if not file.filename or not file.filename.lower().endswith(".md"):
            raise HTTPException(status_code=400, detail="请上传 .md 文件")
        try:
            # 读取上传文件的原始字节内容。
            content = file.file.read()
            # 将文件内容按 UTF-8 编码解码为字符串。
            markdown_text = content.decode("utf-8")
            # 创建 LangChain 文档，并记录原始文件名。
            document = LangchainDocument(page_content=markdown_text, metadata={"filename": file.filename})
            return [document]
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Markdown 文件必须使用 UTF-8 编码")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Markdown解析失败: {e}")

    # 获取 Markdown 章节路径，优先使用切片器生成的 heading_path。
    @staticmethod
    def get_heading_path(metadata: dict) -> str:
        # 优先返回已有的完整章节路径。
        heading_path = metadata.get("heading_path")
        if heading_path:
            return heading_path
        # 兼容旧数据，根据 H1、H2、H3 等标题重建章节路径。
        headers = []
        for key, value in sorted(metadata.items(), key=lambda item: (int(item[0][1:]) if isinstance(item[0], str) and item[0].startswith("H") and item[0][1:].isdigit() else 999)):
            if isinstance(key, str) and key.startswith("H") and key[1:].isdigit() and value:
                headers.append(value)
        return " > ".join(headers)

    # 提取元数据中所有 H1、H2、H3 等标题字段。
    @staticmethod
    def get_headers(metadata: dict) -> dict:
        return {key: value for key, value in metadata.items() if isinstance(key, str) and key.startswith("H") and key[1:].isdigit()}

    """将 Parent、Child 切片及其关联关系导出为 RAG 评测 JSON"""
    def save_evaluation_chunks(self, document: Document, parent_chunks, child_chunks, parent_id_map: dict, filename: str):
        # 根据数据库 Parent ID 对 Child 切片进行分组。
        children_map = {}
        for child in child_chunks:
            database_parent_id = parent_id_map.get(child.parent_id)
            if database_parent_id is None:
                raise ValueError(f"找不到 Child 对应的数据库 Parent ID: {child.parent_id}")
            children_map.setdefault(database_parent_id, []).append(child)
        # 初始化评测数据，记录文档信息和切片数量。
        result = {
            "document_id": document.id, "filename": filename,
            "parent_count": len(parent_chunks), "child_count": len(child_chunks),
            "parents": []
        }
        # 遍历 Parent 切片，构建父级知识块数据。
        for parent_index, parent in enumerate(parent_chunks, start=1):
            # 获取切片器生成的 Parent ID 和对应的数据库 ID。
            splitter_parent_id = parent.parent_id
            database_parent_id = parent_id_map.get(splitter_parent_id)
            if database_parent_id is None:
                raise ValueError(f"找不到数据库 Parent ID: {splitter_parent_id}")
            metadata = parent.metadata or {}
            # 保存 Parent 的章节信息、正文、结构块及子切片列表。
            parent_data = {
                "index": parent_index, "parent_id": database_parent_id,
                "document_id": document.id,
                "heading_path": self.get_heading_path(metadata),
                "headers": self.get_headers(metadata),
                "content": parent.text,
                "blocks": [{"block_type": block_type, "content": block} for block_type, block in parent.blocks],
                "children": []
            }
            # 查找当前 Parent 对应的 Child 切片并记录其元数据。
            parent_children = children_map.get(database_parent_id, [])
            for child_index, child in enumerate(parent_children, start=1):
                parent_data["children"].append({
                    "index": child_index, "child_id": child.child_id,
                    "block_id": child.block_id, "block_type": child.block_type,
                    "chunk_index": child.chunk_index, "content": child.text
                })
            result["parents"].append(parent_data)
        # 根据原始文件名生成对应的 JSON 文件名和保存路径。
        original_filename = Path(filename).name
        output_filename = f"{Path(original_filename).stem}.json"
        output_path = EVALUATION_DIR / output_filename
        # 将评测数据以 UTF-8 编码写入 JSON 文件，并保留中文。
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"✅ RAG评测数据已生成: {output_path}")
        return output_path

    """将文档、Parent、Child 和向量保存到 PostgreSQL，可选导出评测数据"""
    def save_document(self, file, documents, parent_chunks, child_chunks, db: Session,ai_metadata: dict = None, export_evaluation: bool = False,metadata_status: str = "completed", metadata_error: str = None,existing_document: Document = None, replace_existing: bool = False, refresh_index: bool = True, commit: bool = True):
        try:
            # 获取文件名、合并正文，并准备 AI 元数据。
            filename = getattr(file, "filename", "untitled.md")
            raw_content = "\n\n".join(doc.page_content for doc in documents)
            ai_metadata = ai_metadata or {}
            # 优先复用已有文档对象，否则创建新文档。
            new_doc = existing_document or Document(filename=filename, raw_content=raw_content)
            new_doc.filename = filename
            new_doc.raw_content = raw_content
            new_doc.title = ai_metadata.get("title") or Path(filename).stem
            new_doc.summary = ai_metadata.get("summary") or raw_content.strip()[:240]
            new_doc.category = ai_metadata.get("category") or "未分类"
            new_doc.tags = ai_metadata.get("tags") or []
            new_doc.keywords = ai_metadata.get("keywords") or []
            new_doc.metadata_status = metadata_status
            new_doc.metadata_error = metadata_error
            new_doc.processing_status = "processing"
            # 先写入文档并 flush，确保后续切片可以关联文档 ID。
            db.add(new_doc)
            db.flush()
            if replace_existing and existing_document is not None:
                db.query(DocumentChunk).filter(
                    DocumentChunk.document_id == new_doc.id,
                    DocumentChunk.parent_id.is_not(None),
                ).delete(synchronize_session=False)
                db.query(DocumentChunk).filter(
                    DocumentChunk.document_id == new_doc.id,
                    DocumentChunk.parent_id.is_(None),
                ).delete(synchronize_session=False)
            # 创建 Parent 数据库记录，Parent 本身不保存向量。
            parent_orm_chunks = [
                DocumentChunk(
                    document_id=new_doc.id, parent_id=None,
                    block_id=None, block_type=None, chunk_index=None,
                    text=chunk.text, chunk_metadata=chunk.metadata,
                )
                for chunk in parent_chunks
            ]
            db.add_all(parent_orm_chunks)
            db.flush()
            # 建立切片器 Parent ID 到数据库 Parent ID 的映射。
            parent_id_map = {
                chunk.parent_id: orm.id for chunk, orm in zip(parent_chunks, parent_orm_chunks)
            }
            # 创建 Child 数据库记录，并关联对应的 Parent 和向量。
            child_orm_chunks = []
            for chunk in child_chunks:
                database_parent_id = parent_id_map.get(chunk.parent_id)
                if database_parent_id is None:
                    raise ValueError(f"找不到 Parent ID: {chunk.parent_id}")
                child_orm_chunks.append(
                    DocumentChunk(
                        document_id=new_doc.id, parent_id=database_parent_id,
                        block_id=chunk.block_id, block_type=chunk.block_type,
                        chunk_index=chunk.chunk_index, text=chunk.text,
                        chunk_metadata=chunk.metadata, embedding=chunk.embedding,
                    )
                )
            # 批量添加 Child，更新处理状态并提交数据库事务。
            db.add_all(child_orm_chunks)
            new_doc.processing_status = "completed"
            if commit:
                db.commit()
            # 刷新 BM25 索引，使新文档可以参与关键词检索。
            if refresh_index and commit:
                try:
                    retriever.refresh_bm25_index()
                except Exception as exc:
                    print(f"BM25 索引刷新失败，将在后续刷新时重试: {exc}")
            # 按需导出评测 JSON，导出失败不影响已完成的文档入库。
            evaluation_path = None
            if export_evaluation:
                try:
                    evaluation_path = self.save_evaluation_chunks(
                        document=new_doc, parent_chunks=parent_chunks,
                        child_chunks=child_chunks, parent_id_map=parent_id_map,
                        filename=filename,
                    )
                except Exception as exc:
                    print(f"评测数据导出失败，不影响文档入库: {exc}")
            # 刷新文档对象并返回文档记录和评测文件路径。
            if commit:
                db.refresh(new_doc)
            return new_doc, evaluation_path
        except Exception:
            # 数据库操作发生异常时回滚当前事务，并向上层抛出异常。
            db.rollback()
            raise

    """上传处理失败时，将文档状态更新为 failed 并记录错误信息"""
    def _mark_upload_failed(self, db: Session, document_id: str | None, reason: str) -> None:
        # 没有文档 ID 时无法更新数据库，直接返回。
        if not document_id:
            return
        try:
            # 根据文档 ID 查询需要更新状态的记录。
            document = db.query(Document).filter(Document.id == document_id).first()
            if document is not None:
                document.processing_status = "failed"
                # 仅在元数据仍处于处理中时更新其状态。
                if document.metadata_status == "processing":
                    document.metadata_status = "failed"
                # 截断错误原因，避免错误信息过长。
                error = f"文档处理失败：{reason[:800]}"
                document.metadata_error = (
                    f"{document.metadata_error}\n{error}"
                    if document.metadata_error
                    else error
                )
                db.commit()
        except Exception as exc:
            # 状态更新失败时回滚事务并输出日志。
            db.rollback()
            print(f"无法更新文档失败状态: {exc}")

    """上传 Markdown，生成元数据、切片和向量，并完成数据库入库"""
    def upload_markdown(self, file, db: Session, export_evaluation: bool = False):
        document = None
        try:
            # 解析 Markdown 文件并提取正文。
            documents = self.parse_markdown(file)
            markdown_text = documents[0].page_content
            if not markdown_text.strip():
                raise HTTPException(status_code=400, detail="Markdown 文档内容不能为空")
            # 获取文件名，并构建 AI 元数据生成失败时使用的默认值。
            filename = getattr(file, "filename", "untitled.md") or "untitled.md"
            fallback_metadata = {
                "title": Path(filename).stem or "未命名文档",
                "summary": markdown_text.strip()[:240],
                "category": "未分类", "tags": [], "keywords": [],
            }
            # 先创建处理中状态的文档，避免后续处理失败时没有记录可追踪。
            document = Document(
                filename=filename, raw_content=markdown_text,
                title=fallback_metadata["title"], summary=fallback_metadata["summary"],
                category=fallback_metadata["category"], tags=[], keywords=[],
                metadata_status="processing", processing_status="processing",
            )
            db.add(document)
            db.commit()
            db.refresh(document)
            # 调用 AI 生成标题、摘要、分类、标签和关键词。
            metadata_status = "completed"
            metadata_error = None
            try:
                ai_metadata = MetadataService().generate_metadata(markdown_text)
            except Exception as exc:
                # AI 生成失败时使用默认元数据，允许文档继续入库。
                ai_metadata = fallback_metadata
                metadata_status = "failed"
                metadata_error = f"AI 元数据生成失败：{str(exc)[:800]}"
            # 将生成的元数据写回文档对象。
            document.title = ai_metadata.get("title") or fallback_metadata["title"]
            document.summary = ai_metadata.get("summary") or fallback_metadata["summary"]
            document.category = ai_metadata.get("category") or "未分类"
            document.tags = ai_metadata.get("tags") or []
            document.keywords = ai_metadata.get("keywords") or []
            document.metadata_status = metadata_status
            document.metadata_error = metadata_error
            db.commit()
            db.refresh(document)
            # 使用高级 RAG 切分器生成 Parent 和 Child 知识片段。
            splitter = AdvancedRAGSplitter()
            parent_chunks, child_chunks = splitter.process_documents(documents)
            # 将章节路径和正文组合为向量模型的输入文本。
            content_texts = []
            for chunk in child_chunks:
                heading_path = self.get_heading_path(chunk.metadata or {})
                content_texts.append(f"章节路径：\n{heading_path}\n\n正文：\n{chunk.text}")
            # 批量生成 Child 向量，并校验向量数量是否与切片数量一致。
            content_vectors = embedding_service.embed_documents(content_texts)
            if len(content_vectors) != len(child_chunks):
                raise ValueError("向量服务返回的结果数量与文档切片数量不一致")
            # 将生成的向量逐一绑定到对应的 Child 切片。
            for chunk, content_vector in zip(child_chunks, content_vectors):
                chunk.embedding = content_vector
            # 保存文档、Parent、Child 及其向量，并按需导出评测数据。
            document, evaluation_path = self.save_document(
                file=file, documents=documents,
                parent_chunks=parent_chunks, child_chunks=child_chunks, db=db,
                ai_metadata=ai_metadata, export_evaluation=export_evaluation,
                metadata_status=metadata_status, metadata_error=metadata_error,
                existing_document=document,
            )
            # 根据元数据生成状态返回对应提示和处理结果。
            message = "上传完成" if metadata_status == "completed" else "文档已入库，但 AI 元数据生成失败"
            return {
                "message": message, "document_id": document.id,
                "processing_status": document.processing_status,
                "metadata_status": document.metadata_status,
                "metadata_error": document.metadata_error,
                "parent_chunks": len(parent_chunks), "child_chunks": len(child_chunks),
                "evaluation_file": str(evaluation_path) if evaluation_path else None,
            }
        except HTTPException as exc:
            # 发生 HTTP 异常时回滚当前事务，并记录文档处理失败状态。
            db.rollback()
            self._mark_upload_failed(db, document.id if document is not None else None, str(exc.detail))
            raise
        except Exception as exc:
            # 发生其他异常时回滚事务、记录错误并返回 HTTP 500。
            db.rollback()
            self._mark_upload_failed(db, document.id if document is not None else None, str(exc))
            print(f"文档上传处理失败: {exc}")
            raise HTTPException(
                status_code=500,
                detail="文档处理失败，文档状态已保留，请检查错误信息后重试",
            ) from exc
    """通过标准的元数据提取、文本分块和向量化流程处理 Vault 中的 Markdown 文件"""
    def process_markdown_content(self, markdown_text: str, filename: str, db: Session,existing_document: Document | None = None,refresh_index: bool = True) -> Document:
        if not markdown_text.strip():
            raise ValueError("Markdown 文档内容不能为空")
        documents = [LangchainDocument(page_content=markdown_text, metadata={"filename": filename})]
        fallback = {"title": Path(filename).stem or "未命名文档",
                    "summary": markdown_text.strip()[:240], "category": "未分类",
                    "tags": [], "keywords": []}
        metadata_status, metadata_error = "completed", None
        try:
            ai_metadata = MetadataService().generate_metadata(markdown_text)
        except Exception as exc:
            ai_metadata, metadata_status = fallback, "failed"
            metadata_error = f"AI 元数据生成失败：{str(exc)[:800]}"
        parent_chunks, child_chunks = AdvancedRAGSplitter().process_documents(documents)
        texts = [f"章节路径：\n{self.get_heading_path(chunk.metadata or {})}\n\n正文：\n{chunk.text}"
                 for chunk in child_chunks]
        vectors = embedding_service.embed_documents(texts)
        if len(vectors) != len(child_chunks):
            raise ValueError("向量服务返回的结果数量与文档切片数量不一致")
        for chunk, vector in zip(child_chunks, vectors):
            chunk.embedding = vector
        document, _ = self.save_document(
            file=type("MarkdownSource", (), {"filename": filename})(),
            documents=documents, parent_chunks=parent_chunks, child_chunks=child_chunks,
            db=db, ai_metadata=ai_metadata, export_evaluation=False,
            metadata_status=metadata_status, metadata_error=metadata_error,
            existing_document=existing_document,
            replace_existing=existing_document is not None, refresh_index=refresh_index, commit=False,
        )
        return document

# 创建上传服务实例，供接口路由层调用。
upload_service = UploadService()
