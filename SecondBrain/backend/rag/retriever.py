# 向量检索

# 用户问题
#     |
#     v
# Embedding模型
#     |
#     v
# query_vector
#     |
#     v
# pgvector 查询 child_chunks
#     |
#     v
# 得到 child.parent_id
#     |
#     v
# 查询 parent_chunks
#     |
#     v
# 返回父块上下文
#     |
#     v
# LLM回答