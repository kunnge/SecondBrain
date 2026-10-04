# 导入 FastAPI 框架
from fastapi import FastAPI

from app import health, upload, chat
from fastapi.middleware.cors import CORSMiddleware
# 创建 FastAPI 应用对象

app = FastAPI(
# swagger的配置
    # API 名称
    # 会显示在 Swagger 文档页面顶部
    title="知识库 Agent",

    # API 当前版本
    version="0.1.0",

    # API 描述信息
    # 也会显示在 Swagger 文档中
    description="个人知识库 Agent",
    # 开发阶段建议开启
    # 生产环境建议关闭
    # debug=True,
)

# 配置跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8011"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 导入三个接口模块（Router）
# 注册路由（接口）

# 注册健康检查接口
# 例如：
app.include_router(health.router)

# 注册上传接口
# 例如：
app.include_router(upload.router)

# 注册聊天接口
# 例如：
app.include_router(chat.router)