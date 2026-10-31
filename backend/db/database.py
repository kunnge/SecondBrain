
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from config.settings import DATABASE_URL, DB_MAX_OVERFLOW, DB_POOL_SIZE

Base = declarative_base()

# 作用：专门负责 PostgreSQL 连接
class DatabaseManager:
    # 创建 Base 基类
    def __init__(self,database_url:str,pool_size:int = DB_POOL_SIZE,max_overflow:int = DB_MAX_OVERFLOW):
        """初始化数据库连接"""
        self.database_url = database_url
        # 创建 Engine
        self.engine = create_engine(database_url,pool_pre_ping=True,pool_size=pool_size,max_overflow=max_overflow)
        # 创建 Session 工厂
        self.SessionLocal = sessionmaker(autocommit=False,autoflush=False,bind=self.engine)
    def get_db(self):
        """给 FastAPI 接口提供数据库 Session（会话对象),可以操作数据库"""
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()
    def init_db(self):
        """初始化数据库"""
        # 关键：先导入所有模型，让 SQLAlchemy 注册表
        import db.models
        # 开启 pgvector
        with self.engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
        # 创建所有表
        # print("初始化前注册的表：", list(Base.metadata.tables.keys()))
        Base.metadata.create_all(bind=self.engine)
        # print("初始化后数据库中的表：", self.engine.dialect.get_table_names(self.engine.connect()))
        print("数据库初始化完成")

# 连接数据库并初始化
db_manager = DatabaseManager(DATABASE_URL)
db_manager.init_db()
