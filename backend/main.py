# 导入 FastAPI 框架
from contextlib import asynccontextmanager

from fastapi import FastAPI

from agents.knowledge_agent import knowledge_agent
from api import upload, chat, health, evaluation, documents, obsidian
from services.obsidian_sync_service import obsidian_sync_service
from db.database import db_manager
from fastapi.middleware.cors import CORSMiddleware
from config.settings import APP_VERSION, CHECKPOINTER_DATABASE_URL, CORS_ORIGINS, LANGGRAPH_STRICT_MSGPACK


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import os
    os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", LANGGRAPH_STRICT_MSGPACK)
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    # 每次应用程序启动后，都要重新检查数据库表，确认无误后再接受请求
    db_manager.init_db()
    obsidian_sync_service.mark_interrupted_jobs()

    async with AsyncPostgresSaver.from_conn_string(CHECKPOINTER_DATABASE_URL) as checkpointer:
        await checkpointer.setup()
        knowledge_agent.set_checkpointer(checkpointer)
        yield
# 创建 FastAPI 应用对象

app = FastAPI(
# swagger的配置
    # API 名称
    # 会显示在 Swagger 文档页面顶部
    title="知识库 Agent",

    # API 当前版本
    version=APP_VERSION,

    # API 描述信息
    # 也会显示在 Swagger 文档中
    description="个人知识库 Agent",
    lifespan=lifespan,
    # 开发阶段建议开启
    # 生产环境建议关闭
    # debug=True,
)

# 配置跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 导入三个接口模块（Router）
# 注册路由（接口）

# 注册健康检查接口
app.include_router(health.router)

# 注册上传接口
app.include_router(upload.router)
app.include_router(documents.router)

# 注册聊天接口
app.include_router(chat.router)

# 注册测试接口
app.include_router(evaluation.router)
app.include_router(obsidian.router)
