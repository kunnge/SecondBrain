# 文档切分与检索逻辑
## 切割逻辑
1. 读取 UTF-8 Markdown，解析为 Markdown 结构块。标题、段落、代码块、列表和表格会被识别并保留类型及文档顺序。
2. 根据标题层级维护章节路径，例如 `一级标题 > 二级标题`。标题路径会写入块元数据，后续也会拼到子块的 Embedding 文本前，帮助检索理解片段所在章节。
3. 把相邻结构块组合为父块。默认目标大小为 1,200 个字符；只有在加入下一个完整结构块会超过目标时才开启新的父块。因此父块边界优先尊重 Markdown 结构，单个超长结构块可能使父块超过目标大小。
4. 父块不超过 500 个字符时，直接生成一个子块。更长的父块按原始结构块进一步拆成子块：普通文本和列表使用递归字符切分，默认 500 字符、50 字符重叠；优先按空行、换行、中文句末标点、空格等边界切分。代码块切分后保留围栏和语言标记；表格按数据行切分，并在每个子表中重复表头和分隔行。不可再分的长行或长结构块仍可能超过目标长度。
5. 每个子块保存父块 ID、块类型、块序号、章节路径等信息。子块 Embedding 的输入格式为 `章节路径：...\n\n正文：...`，使用配置的中文 Embedding 模型生成 512 维向量并写入 PostgreSQL/pgvector；父块保存完整文本，供后续重排和回答使用。
## 检索逻辑
1. 查询向量：Search 使用与入库相同的 Embedding 模型编码问题。
2. 两路子块召回：向量通道在 pgvector 中按向量距离召回近邻子块；BM25 通道基于 Jieba 搜索模式分词，在内存索引中按关键词匹配召回。默认两路都最多取 `child_top_k` 个候选；若请求指定 `document_id`，检索会限制在该文档中。BM25 索引在应用启动时建立，文档入库或 Obsidian 同步后刷新。
3. RRF 融合：两路结果按各自名次合并，而不是直接比较向量距离和 BM25 原始分数。某子块在两路都出现时会叠加贡献，融合分数为各路 `1 / (RRF_K + 名次)` 之和；默认 `RRF_K=100`。融合后保留至多 `child_top_k` 个子块。
4. 父块去重：将子块候选按父块归组，每个父块暂以其最高 RRF 子块代表，父块按该分数排序。
5. CrossEncoder 重排：取一批候选父块，将问题与父块完整正文及章节路径一起交给本地 reranker 打分，最后保留 `parent_top_k` 个父块。默认 `parent_top_k=4`。重排候选数配置为 `max(parent_top_k × 4, 26)`，但不会超过可用候选数；默认聊天的子块候选上限为 12，因此此时实际上最多只能重排 12 个候选父块。
6. 邻块扩展：检索器还会围绕命中子块，在同一父块、同一原始结构块（`block_id`）内取前后相邻子块，默认窗口为每侧 1 块；再按每个父块最多 3 块、总计最多 12 块去重和排序。
7. 交给 Agent：当前 Agent 读取检索结果中的 `results`，将重排后的父块正文作为回答上下文，并用这些父块构建来源卡片。检索器同时返回了 `context_chunks`（邻块扩展结果），但当前 Agent 没有将该字段放入模型提示词或来源列表；因此第 6 步目前是检索器已计算的结果，不是当前聊天回答实际使用的上下文。

# 本地运行

### 配置环境变量
后端从启动进程可见的环境变量和 `.env` 读取配置

| 变量                          | 用途                         | 默认值/说明                                                       |
| --------------------------- | -------------------------- | ------------------------------------------------------------ |
| `DEEPSEEK_API_KEY`          | DeepSeek 聊天及文档元数据调用密钥      | 必填(放在.env)                                                   |
| `DEEPSEEK_BASE_URL`         | DeepSeek API 地址            | `https://api.deepseek.com`                                   |
| `DEEPSEEK_MODEL`            | Agent 对话模型                 | `deepseek-flash`                                             |
| `METADATA_MODEL`            | 文档摘要、分类、标签及关键词生成模型         | `deepseek-chat`                                              |
| `DATABASE_URL`              | SQLAlchemy 主数据库连接          | `postgresql+psycopg2://USER:PASSWORD@HOST:5432/DB_NAME`      |
| `CHECKPOINTER_DATABASE_URL` | LangGraph checkpoint 数据库连接 | 留空时从 `DATABASE_URL` 派生；单独配置时使用 psycopg 3 可识别的 PostgreSQL DSN |
| `DEFAULT_USER_ID`           | 当前开发模式下的默认用户标识             | `dev-user`；不是登录账号                                            |
| `CORS_ORIGINS`              | 允许跨域访问的来源，逗号分隔             | `http://localhost:8011,http://localhost:8012`                |
| `OBSIDIAN_VAULT_PATH`       | Obsidian Vault 本地绝对路径      | 默认 `E:\note`；同步功能要求目录存在                                      |
| `VITE_API_BASE_URL`         | 前端 API 基础地址                | 开发环境留空时使用 Vite 代理                                            |

## 启动后端
第一步
```
cd SecondBrain/backend
```
第二步
```
pip install -r requirements.txt
```
第三步
```
uvicorn main:app --reload
```
## 启动前端
第一步
```cmd
cd SecondBrain/frontend
```
第二步
```
npm install
```
第三步
```
npm run dev
```
## 后端 HTTP API

默认 API 地址为 `http://127.0.0.1:8000`
### 1.健康检查、上传和文档

| 方法与路径                          | 输入                                           | 用途/返回                                             |
| ------------------------------ | -------------------------------------------- | ------------------------------------------------- |
| `GET /health`                  | 无                                            | 健康检查，返回 `{"status":"ok,health"}`                  |
| `POST /upload/md`              | `multipart/form-data`，字段名 `file`             | 上传并处理 `.md` 文件，返回文档元数据和处理状态                       |
| `GET /documents`               | 查询参数 `q`、`category`、`tag`、`page`、`page_size` | 分页文档列表，含 `items`、`total`、页数、分类和标签选项               |
| `GET /documents/{document_id}` | 文档 ID                                        | 获取文档详情，含 Markdown 正文                              |
| `PUT /documents/{document_id}` | JSON 元数据字段                                   | 更新 `title`、`summary`、`category`、`tags`、`keywords` |

### 2.会话与聊天

| 方法与路径                                                                    | 输入                         | 用途/返回                                                |
| ------------------------------------------------------------------------ | -------------------------- | ---------------------------------------------------- |
| `GET /conversations`                                                     | 可选 `include_archived=true` | 列出当前默认用户会话，按更新时间倒序；默认隐藏归档会话                          |
| `POST /conversations`                                                    | `{"title":"可选标题"}` 或 `{}`  | 创建会话并返回会话 ID、标题及时间                                   |
| `GET /conversations/{conversation_id}`                                   | 会话 ID                      | 获取会话信息                                               |
| `GET /conversations/{conversation_id}/messages`                          | 会话 ID                      | 按序返回消息正文；当前历史响应的 `sources` 为空、`status` 为 `completed` |
| `PATCH /conversations/{conversation_id}`                                 | `{"title":"新标题"}`          | 重命名会话                                                |
| `PATCH /conversations/{conversation_id}/archive`                         | `{"is_archived":true}`     | 设置归档状态；这是 API，页面尚未提供归档控件                             |
| `DELETE /conversations/{conversation_id}`                                | 无                          | 删除会话及关联消息，返回 `{"deleted":true}`                      |
| `POST /conversations/chat`                                               | 聊天 JSON，见下文                | 提交新问题并返回 SSE                                         |
| `POST /conversations/{conversation_id}/messages/{message_id}/edit`       | 编辑 JSON，见下文                | 编辑用户提问并流式生成新回答                                       |
| `POST /conversations/{conversation_id}/messages/{message_id}/regenerate` | 重答 JSON，见下文                | 重生成指定 AI 回答                                          |


