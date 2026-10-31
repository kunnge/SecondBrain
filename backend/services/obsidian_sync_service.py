import hashlib
import logging
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from config.settings import OBSIDIAN_VAULT_PATH
from db.database import db_manager
from db.models import Document, DocumentChunk, ObsidianSyncFile, ObsidianSyncJob
from rag.retriever import retriever
from services.upload_service import upload_service

# 获取当前模块的日志记录器
logger = logging.getLogger(__name__)

class ObsidianSyncService:

    """获取并校验 Obsidian Vault 目录"""
    @staticmethod
    def vault_path() -> Path:
        if not OBSIDIAN_VAULT_PATH:
            raise ValueError("未配置 OBSIDIAN_VAULT_PATH")
        path = Path(OBSIDIAN_VAULT_PATH).expanduser()
        if not path.exists() or not path.is_dir():
            raise ValueError(f"Obsidian Vault 目录不存在或不是目录：{path}")
        return path.resolve()

    """递归扫描 Vault，返回 Markdown 文件列表和扫描错误"""
    @staticmethod
    def scan(vault: Path) -> tuple[list[Path], list[str]]:
        found = []
        scan_errors = []
        # 判断文件或目录是否为隐藏项
        def is_hidden(path: Path) -> bool:
            if path.name.startswith("."):
                return True
            try:
                attributes = path.stat().st_file_attributes
                return bool(attributes & stat.FILE_ATTRIBUTE_HIDDEN)
            except (AttributeError, OSError):
                return False
        # 记录目录遍历过程中发生的错误
        def onerror(error):
            scan_errors.append(str(error))
        # 遍历 Vault，跳过 Obsidian 配置目录和隐藏目录
        for root, dirs, files in os.walk(vault, onerror=onerror):
            dirs[:] = sorted(d for d in dirs if d != ".obsidian" and not is_hidden(Path(root) / d))
            for name in sorted(files):
                path = Path(root) / name
                if is_hidden(path) or path.suffix.lower() != ".md":
                    continue
                found.append(path)
        # 按相对路径排序，保证扫描结果顺序稳定
        return sorted(found, key=lambda p: p.relative_to(vault).as_posix()), scan_errors

    """将上次程序异常退出后遗留的任务标记为失败"""
    def mark_interrupted_jobs(self) -> None:
        db = db_manager.SessionLocal()
        try:
            db.query(ObsidianSyncJob).filter(
                ObsidianSyncJob.status.in_(("queued", "running"))
            ).update({ObsidianSyncJob.status: "failed",
                      ObsidianSyncJob.completed_at: datetime.now(timezone.utc),
                      ObsidianSyncJob.current_file: None}, synchronize_session=False)
            db.commit()
        finally:
            db.close()

    """根据任务 ID 查询同步任务，不存在时抛出异常"""
    @staticmethod
    def _job(db: Session, job_id: UUID) -> ObsidianSyncJob:
        job = db.query(ObsidianSyncJob).filter(ObsidianSyncJob.id == job_id).first()
        if job is None:
            raise LookupError("同步任务不存在")
        return job

    """执行完整的 Obsidian Markdown 同步任务"""
    def run_job(self, job_id: UUID) -> None:
        db = db_manager.SessionLocal()
        changed = False  # 标记文档数据是否发生变化，用于决定是否刷新 BM25 索引
        try:
            # 将任务状态更新为运行中，并记录开始时间
            job = self._job(db, job_id)
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            db.commit()

            # 检查 Vault 路径并扫描所有 Markdown 文件
            vault = self.vault_path()
            paths, scan_errors = self.scan(vault)

            # 扫描不完整时停止任务，避免把未扫描到的文件误判为已删除
            if scan_errors:
                raise OSError("Vault 扫描不完整，已停止以避免误删：" + "; ".join(scan_errors[:5]))

            # 保存本次扫描到的文件数量
            job = self._job(db, job_id)
            job.scanned_count = len(paths)
            db.commit()
            present = set()  # 记录本次扫描中实际存在的相对路径

            # 逐个处理扫描到的 Markdown 文件
            for path in paths:
                relative = path.relative_to(vault).as_posix()
                present.add(relative)
                digest = None

                # 更新当前正在处理的文件路径，方便前端展示进度
                job = self._job(db, job_id)
                job.current_file = relative
                db.commit()

                try:
                    # 读取文件内容并计算 SHA-256 哈希，用于判断内容是否变化
                    content_bytes = path.read_bytes()
                    digest = hashlib.sha256(content_bytes).hexdigest()
                    content = content_bytes.decode("utf-8")

                    # 查询文件同步记录及其关联的知识库文档
                    record = db.query(ObsidianSyncFile).filter_by(relative_path=relative).first()
                    existing = db.query(Document).filter_by(id=record.document_id).first() if record and record.document_id else None

                    # 文件内容未变化且已有有效文档时跳过重复处理
                    if record and record.status == "completed" and record.content_hash == digest and existing:
                        job.skipped_count += 1
                        db.commit()
                        continue

                    # 文件路径过长时使用文件名作为知识库文档名称
                    filename = relative if len(relative) <= 255 else path.name

                    # 复用上传服务处理 Markdown，并暂不刷新检索索引
                    doc = upload_service.process_markdown_content(
                        content, filename, db, existing_document=existing, refresh_index=False,
                    )

                    # 新文件创建同步记录，已有记录则更新同步信息
                    if record is None:
                        record = ObsidianSyncFile(relative_path=relative, content_hash=digest,
                                                  document_id=doc.id, status="completed")
                        db.add(record)
                        job.added_count += 1
                    else:
                        record.content_hash = digest
                        record.document_id = doc.id
                        record.status = "completed"
                        record.error = None
                        if existing:
                            job.updated_count += 1
                        else:
                            job.added_count += 1

                    # 记录本次成功同步的时间，并提交数据库事务
                    record.synced_at = datetime.now(timezone.utc)
                    db.flush()
                    db.commit()
                    changed = True

                except Exception as exc:
                    # 单个文件处理失败时回滚当前事务，并记录失败原因
                    db.rollback()
                    record = db.query(ObsidianSyncFile).filter_by(relative_path=relative).first()

                    # 首次同步失败时也创建记录，便于后续重试和排查
                    if record is None:
                        record = ObsidianSyncFile(relative_path=relative,
                                                  content_hash=digest or hashlib.sha256(b"").hexdigest(),
                                                  status="failed")
                        db.add(record)

                    # 更新文件失败状态，并累计任务失败数量和错误明细
                    record.status = "failed"
                    record.error = str(exc)[:2000]
                    job = self._job(db, job_id)
                    job.failed_count += 1
                    job.errors = (job.errors or []) + [{"path": relative, "error": str(exc)[:2000]}]
                    db.commit()
                    logger.exception("Obsidian 文件同步失败：%s", relative)

            # 查询所有尚未标记删除的历史同步记录
            tracked = db.query(ObsidianSyncFile).filter(
                ObsidianSyncFile.status != "deleted"
            ).all()

            # 将本次扫描中已不存在的文件从知识库中删除
            for record in tracked:
                if record.relative_path in present:
                    continue

                # 只有确认路径不存在时才执行删除，读取失败的文件仍在 present 中
                if record.document_id:
                    doc = db.query(Document).filter_by(id=record.document_id).first()
                    if doc:
                        # 先删除子分块，再删除父分块，避免外键约束冲突
                        db.query(DocumentChunk).filter(
                            DocumentChunk.document_id == doc.id,
                            DocumentChunk.parent_id.is_not(None),
                        ).delete(synchronize_session=False)
                        db.query(DocumentChunk).filter(
                            DocumentChunk.document_id == doc.id,
                            DocumentChunk.parent_id.is_(None),
                        ).delete(synchronize_session=False)
                        db.delete(doc)
                        job = self._job(db, job_id)
                        job.deleted_count += 1
                        changed = True

                # 保留同步记录，但清除文档关联并标记为已删除
                record.document_id = None
                record.status = "deleted"
                record.error = None
                db.commit()

            # 文档发生新增、更新或删除后，重新构建 BM25 索引
            if changed:
                try:
                    retriever.refresh_bm25_index()
                except Exception:
                    logger.exception("刷新 BM25 索引失败")

            # 更新任务最终状态、完成时间和扫描错误信息
            job = self._job(db, job_id)
            job.status = "completed"
            job.current_file = None
            job.completed_at = datetime.now(timezone.utc)
            job.errors = (job.errors or []) + [{"path": None, "error": error} for error in scan_errors]
            db.commit()

        except Exception as exc:
            # 任务级异常发生时回滚事务并记录错误日志
            db.rollback()
            logger.exception("Obsidian 同步任务失败")
            try:
                # 将整个任务标记为失败，并保存异常信息
                job = self._job(db, job_id)
                job.status = "failed"
                job.failed_count += 1
                job.current_file = None
                job.completed_at = datetime.now(timezone.utc)
                job.errors = (job.errors or []) + [{"path": None, "error": str(exc)[:2000]}]
                db.commit()
            except Exception:
                db.rollback()
        finally:
            # 无论任务成功还是失败，都关闭数据库会话
            db.close()

# 创建同步服务单例，供路由和其他模块调用
obsidian_sync_service = ObsidianSyncService()