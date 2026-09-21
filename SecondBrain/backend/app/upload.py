from fastapi import APIRouter, UploadFile, File

from backend.services.upload_service import upload_service
from fastapi.params import Depends
from sqlalchemy.orm import Session

from backend.services.upload_service import DatabaseManager

from backend.services.upload_service import db_manager

# 上传业务接口
router = APIRouter()

@router.post("/upload/md")
async def upload(file: UploadFile = File(...), db: Session = Depends(db_manager.get_db)):
    return upload_service.upload_markdown(file,db)