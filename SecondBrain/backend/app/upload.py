from fastapi import APIRouter, UploadFile, File

from fastapi.params import Depends
from sqlalchemy.orm import Session

from db.database import db_manager
from services.upload_service import upload_service

# 上传业务接口
router = APIRouter()

@router.post("/upload/md")
async def upload(file: UploadFile = File(...), db: Session = Depends(db_manager.get_db)):
    return upload_service.upload_markdown(file,db,True)