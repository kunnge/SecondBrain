from fastapi import APIRouter
# 健康检查接口
router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok,health"}