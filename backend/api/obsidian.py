from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.database import db_manager
from db.models import ObsidianSyncJob
from services.obsidian_sync_service import obsidian_sync_service


# 将同步任务 ORM 对象转换为字典，供接口返回
def serialize(job: ObsidianSyncJob) -> dict:
    return {
        "id": str(job.id), "status": job.status, "scanned_count": job.scanned_count,
        "added_count": job.added_count, "updated_count": job.updated_count,
        "skipped_count": job.skipped_count, "deleted_count": job.deleted_count,
        "failed_count": job.failed_count, "current_file": job.current_file,
        "errors": job.errors or [], "created_at": job.created_at,
        "started_at": job.started_at, "completed_at": job.completed_at,
    }


# 创建 Obsidian 同步路由，统一使用 /obsidian 前缀
router = APIRouter(prefix="/obsidian", tags=["Obsidian"])

# 创建 Obsidian 同步任务，并将实际同步工作放入后台执行
@router.post("/sync", status_code=202)
async def start_sync(background_tasks: BackgroundTasks, db: Session = Depends(db_manager.get_db)):
    # 检查 Obsidian Vault 路径是否有效，配置异常时返回 400
    try:
        obsidian_sync_service.vault_path()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 创建排队中的同步任务，并通过 active_lock 防止多个任务同时执行
    try:
        job = ObsidianSyncJob(status="queued", active_lock=1)
        db.add(job)
        db.commit()
        db.refresh(job)  # 刷新对象，获取数据库生成的字段值
    except IntegrityError as exc:
        # 任务创建失败时回滚事务，通常表示已有任务占用同步锁
        db.rollback()
        raise HTTPException(status_code=409, detail="已有 Obsidian 同步任务正在执行") from exc
    # 将同步任务加入后台队列，接口无需等待同步完成
    background_tasks.add_task(obsidian_sync_service.run_job, job.id)
    # 返回任务信息，客户端可通过任务 ID 查询执行进度
    return serialize(job)

# 根据任务 ID 查询 Obsidian 同步任务的状态和执行结果
@router.get("/sync/{task_id}")
def get_sync(task_id: UUID, db: Session = Depends(db_manager.get_db)):
    # 根据 UUID 查询任务记录
    job = db.query(ObsidianSyncJob).filter(ObsidianSyncJob.id == task_id).first()
    # 任务不存在时返回 404
    if job is None:
        raise HTTPException(status_code=404, detail="同步任务不存在")
    # 返回任务状态、文件统计数量、错误信息和执行时间
    return serialize(job)