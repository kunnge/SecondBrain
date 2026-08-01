from fastapi import APIRouter, UploadFile

from backend.services.upload_service import upload_service

# 上传业务接口
router = APIRouter()

@router.post("/upload/md")
async def upload(file:UploadFile):
    return   upload_service.upload_markdown(file)