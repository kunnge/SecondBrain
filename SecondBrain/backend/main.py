# 导入 FastAPI 框架
from fastapi import FastAPI

from backend.app import health, upload, chat
from backend.database.database import init_db

# 服务启动时，初始化数据库（建扩展、建表）
print("开始初始化数据库")
init_db()
print("初始化完成")
# 创建 FastAPI 应用对象
# 以后所有接口都会挂载到这个 app 上


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


# 导入三个接口模块（Router）
# ===========================
# 注册路由（接口）
# ===========================

# 注册健康检查接口
# 例如：
app.include_router(health.router)

# 注册上传接口
# 例如：
app.include_router(upload.router)

# 注册聊天接口
# 例如：
app.include_router(chat.router)