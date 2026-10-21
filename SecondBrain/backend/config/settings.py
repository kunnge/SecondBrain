import os
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# 数据库配置

# 主数据库连接地址，未配置时使用本地 PostgreSQL 默认地址
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/knowledge_base")
# 默认用户 ID，用于开发环境下标识当前用户
DEFAULT_USER_ID = os.getenv("DEFAULT_USER_ID", "dev-user")
# LangGraph 检查点数据库地址，默认复用主数据库地址并移除 psycopg2 驱动标识
CHECKPOINTER_DATABASE_URL = os.getenv("CHECKPOINTER_DATABASE_URL", DATABASE_URL.replace("+psycopg2", ""))
# 数据库连接池的常规连接数量，默认维持 10 个连接
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
# 连接池允许临时超出的连接数量，默认最多额外创建 20 个连接
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))

# 应用配置

# 应用版本号，默认使用 0.1.0
APP_VERSION = os.getenv("APP_VERSION", "0.1.0")
# LangGraph 消息序列化相关配置，默认读取字符串 true
LANGGRAPH_STRICT_MSGPACK = os.getenv("LANGGRAPH_STRICT_MSGPACK", "true")
# 读取允许跨域访问的前端地址，按逗号拆分并去除空白项
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:8011,http://localhost:8012").split(",") if origin.strip()]

# 模型 API 配置

# DeepSeek API 密钥，没有配置时返回 None
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
# DeepSeek API 请求地址
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
# 默认用于对话生成的模型名称
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
# 默认用于文档元数据生成的模型名称
METADATA_MODEL = os.getenv("METADATA_MODEL", "deepseek-chat")
# 模型生成温度，数值越低通常输出越稳定
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
# 单次模型生成允许的最大 Token 数量
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "2048"))

# 聊天与 Agent 配置

# 聊天检索默认返回数量
CHAT_DEFAULT_TOP_K = int(os.getenv("CHAT_DEFAULT_TOP_K", "4"))
# 聊天接口允许设置的最大检索数量
CHAT_MAX_TOP_K = int(os.getenv("CHAT_MAX_TOP_K", "20"))
# Agent 工具允许使用的最大检索数量
AGENT_TOOL_MAX_TOP_K = int(os.getenv("AGENT_TOOL_MAX_TOP_K", "8"))
# LangGraph 工作流允许的最大递归步数
AGENT_RECURSION_LIMIT = int(os.getenv("AGENT_RECURSION_LIMIT", "8"))
# 用户问题或相关文本允许的最大字符长度
MAX_QUERY_LENGTH = int(os.getenv("MAX_QUERY_LENGTH", "20000"))

# 检索与文档处理配置

# 子块检索默认候选数量
RETRIEVAL_CHILD_TOP_K = int(os.getenv("RETRIEVAL_CHILD_TOP_K", "12"))
# 父块检索默认返回数量
RETRIEVAL_PARENT_TOP_K = int(os.getenv("RETRIEVAL_PARENT_TOP_K", "4"))
# 根据目标数量计算子块候选数时使用的倍数
RETRIEVAL_CHILD_MULTIPLIER = int(os.getenv("RETRIEVAL_CHILD_MULTIPLIER", "3"))
# 重排序阶段使用的父块候选数量下限或目标值，具体取决于调用代码
RERANK_MIN_PARENT_K = int(os.getenv("RERANK_MIN_PARENT_K", "12"))
# 检索到目标块后，允许向前后扩展的相邻块窗口大小
CONTEXT_NEIGHBOR_WINDOW = int(os.getenv("CONTEXT_NEIGHBOR_WINDOW", "1"))
# 每个父块最多保留的子块数量
CONTEXT_MAX_CHUNKS_PER_PARENT = int(os.getenv("CONTEXT_MAX_CHUNKS_PER_PARENT", "3"))
# 最终上下文允许包含的最大块数量
CONTEXT_MAX_TOTAL_CHUNKS = int(os.getenv("CONTEXT_MAX_TOTAL_CHUNKS", "12"))
# 父块的目标切分大小
PARENT_CHUNK_SIZE = int(os.getenv("PARENT_CHUNK_SIZE", "1200"))
# 子块的目标切分大小
CHILD_CHUNK_SIZE = int(os.getenv("CHILD_CHUNK_SIZE", "500"))
# 相邻子块之间保留的重叠字符数
CHILD_CHUNK_OVERLAP = int(os.getenv("CHILD_CHUNK_OVERLAP", "50"))
# 文本向量化模型名称
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
# 本地 Embedding 模型目录
EMBEDDING_MODEL_PATH = os.getenv("EMBEDDING_MODEL_PATH", "models/bge-small-zh-v1.5")
# 本地重排序模型目录
RERANKER_MODEL_PATH = os.getenv("RERANKER_MODEL_PATH", "models/bge-reranker-base")
# 重排序模型单次输入允许的最大 Token 长度
RERANKER_MAX_LENGTH = int(os.getenv("RERANKER_MAX_LENGTH", "512"))
# 重排序模型每批处理的文本数量
RERANKER_BATCH_SIZE = int(os.getenv("RERANKER_BATCH_SIZE", "4"))
# 文档查询条件允许的最大字符长度
MAX_DOCUMENT_QUERY_LENGTH = int(os.getenv("MAX_DOCUMENT_QUERY_LENGTH", "200"))
# 文档列表默认每页返回数量
DOCUMENT_PAGE_SIZE = int(os.getenv("DOCUMENT_PAGE_SIZE", "8"))
# 文档列表单页允许返回的最大数量
DOCUMENT_MAX_PAGE_SIZE = int(os.getenv("DOCUMENT_MAX_PAGE_SIZE", "100"))

# 检索评估客户端配置

# 后端 API 服务地址，默认使用本地 8000 端口
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
# 检索评估请求的超时时间，单位为秒
EVALUATION_REQUEST_TIMEOUT = int(os.getenv("EVALUATION_REQUEST_TIMEOUT", "30"))