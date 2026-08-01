# 负责连接数据库

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

# 1. 数据库连接 URL配置
# 推荐格式: postgresql+psycopg2://用户名:密码@主机地址:端口/数据库名
SQLALCHEMY_DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/knowledge_base"

# 2. 创建 SQLAlchemy Engine
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,  # 每次从连接池获取连接时测试连接是否存活（防止数据库重启导致报错）
    pool_size=10,        # 连接池基础大小
    max_overflow=20      # 最大溢出连接数
)

# 3. 创建 Session 局部工厂
# autocommit=False 保证我们可以手动控制事务，出了问题可以 rollback
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. 创建 Base 基类（供你 document.py 继承使用）
Base = declarative_base()

# 5. 定义依赖注入函数（如果你用的是 FastAPI，这个函数极其重要）
def get_db():
    """
    提供数据库会话 (Session) 的生成器。
    确保每次请求结束后，无论成功或抛出异常，都会关闭会话回收连接。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 6. 数据库初始化方法 (在项目启动时调用)
def init_db():
    """
    初始化数据库：开启 pgvector 扩展并创建所有表。
    """
    # 坑点注意：必须在建表前先启用 vector 扩展！否则包含 Vector 字段的表会创建失败。
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.commit()

    # 局部导入模型，让 SQLAlchemy 扫描到你的 Base 子类（防止循环导入）
    # 假设你的 document.py 放在 app/models/document.py

    # 创建定义在 Base 上的所有表
    Base.metadata.create_all(bind=engine)