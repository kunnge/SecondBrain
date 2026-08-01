# 最终架构（V8）

```text
                        Knowledge Agent

                         Vue3 + Vite
                              │
                     Chat / Knowledge UI
                              │
                         FastAPI API
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   Chat Service        Knowledge Service      File Service
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │
                     LangGraph Workflow
                              │
 ┌─────────────┬──────────────┬──────────────┬──────────────┐
 │             │              │              │              │
Memory      Retriever      Planner        Tool Hub     Knowledge Graph
 │             │              │              │              │
 └─────────────┴──────────────┴──────────────┴──────────────┘
                              │
                      PostgreSQL + pgvector
                              │
             Markdown / PDF / Word / Web / GitHub
```

> **核心调整：**
> 
> - **V1~V4 使用 PostgreSQL + pgvector，不使用 Milvus。**
>     
> - 等知识量很大（几十万 Chunk）再替换为 Milvus。
>     

---

# V1：知识库 MVP（2~3 周）

## 目标

打造一个**真正能每天使用**的知识库，而不是 Demo。

---

## 功能

```text
上传 Markdown

↓

解析 Markdown

↓

Chunk

↓

Embedding

↓

保存 PostgreSQL(pgvector)

↓

聊天问答
```

---

## 支持

- Markdown
    
- PDF（可选）
    
- Word（可选）
    

因为你主要写 Markdown，所以：

> **Markdown 是第一优先级。**

---

## 数据库

```
document
```

```
chunk
```

```
embedding
```

---

## 技术

- FastAPI
    
- PostgreSQL
    
- pgvector
    
- LangChain（文档加载、切分、Embedding）
    
- OpenAI/DeepSeek API
    

---

## 学到

- RAG 全流程
    
- PostgreSQL 基础
    
- 向量检索
    
- FastAPI
    

---

# V2：真正的知识管理

现在开始像 Obsidian。

## 新增功能

```
Document

↓

自动分类

↓

自动Tag

↓

自动摘要

↓

自动关键词
```

数据库：

```
Document

Title

Summary

Category

Tag

Keywords

CreateTime

UpdateTime
```

开始真正管理知识。

---

## 新增能力

例如：

```
最近新增：

LangGraph
```

AI：

```
自动摘要：

……
```

---

## 学到

LLM 不只是回答问题。

还可以：

- 分类
    
- 标签
    
- 摘要
    
- 信息抽取
    

---

# V3：聊天升级

很多人做到这里结束了。

但是真正产品：

聊天必须：

```
聊天

↓

引用来源

↓

点击原文

↓

高亮Chunk
```

例如：

```
Runnable是什么？
```

回答：

```
Runnable是...

来源：

LangChain.md

↓

点击跳转
```

真正像 NotebookLM。

---

## 新增

聊天记录。

数据库：

```
conversation

message
```

---

# V4：Knowledge Agent

终于加入：

LangGraph。

但是：

不要：

Planner。

不要：

多Agent。

只做：

```
用户

↓

Agent

↓

是否搜索？

↓

Search Tool

↓

回答
```

真正开始：

Tool Calling。

---

## Tool

```
Search
```

```
List Document
```

```
Delete
```

```
Summary
```

四个足够。

---

# V5：Memory

很多教程：

Memory：

就是聊天历史。

其实不是。

你的 Memory：

应该包括：

```
Preference

Learning Goal

Current Project

Favorite Language

Favorite Framework
```

例如：

```
以后解释简单一点。
```

自动保存。

以后：

一直生效。

---

## 数据库

```
memory
```

---

# V6：Learning Assistant

开始变成：

学习助手。

例如：

```
我最近学习了什么？
```

AI：

```
最近：

LangGraph

Prompt

RAG

建议：

学习State。
```

不是搜索。

而是：

分析。

---

## 新增

```
Learning Timeline
```

数据库：

```
learning_record
```

---

# V7：Knowledge Graph

这是最值得做的一步。

Markdown：

```
# LangGraph

## State

## Node

## Edge
```

自动：

```
LangGraph

↓

State

↓

Node

↓

Edge
```

建立：

知识关系。

以后：

```
Runnable
```

AI：

不仅回答。

还会推荐：

```
Chain

Prompt

Tool
```

---

## 数据库

```
entity
```

```
relation
```

---

# V8：Planner Agent（真正 Agent）

这才是真正 Agent。

例如：

```
帮我学习 LangGraph。
```

Agent：

```
Planner

↓

搜索知识

↓

生成学习路线

↓

安排今天学习

↓

保存Memory

↓

生成FlashCard

↓

回答
```

开始：

真正规划。

---

# 工程化（从 V2 开始同步推进）

很多教程最后都会留下一个 `main.py`，所有代码都堆在一起。

建议从 V2 起就采用清晰的分层，例如：

```text
backend/
├── api/              # 接口层
├── agents/           # LangGraph Agent
├── services/         # 业务逻辑
├── repositories/     # 数据访问
├── models/           # ORM 模型
├── schemas/          # Pydantic
├── tools/            # Agent Tool
├── rag/              # 检索、Embedding、Chunk
├── parsers/          # Markdown/PDF 解析
├── prompts/          # Prompt 模板
├── memory/           # Memory 管理
├── config/
├── tests/
└── main.py
```

这样以后增加功能时，不需要推翻重来。

---

# 我还建议增加一个 V0

这是我最想补充的一点，也是很多人容易忽略的。

在正式开发之前，先花几天做一个 **V0：技术验证（PoC）**。

目标只有一个：

> **验证整条 RAG 链路是否可行。**

流程如下：

```text
Markdown

↓

读取

↓

Chunk

↓

Embedding

↓

PostgreSQL(pgvector)

↓

Retriever

↓

DeepSeek

↓

回答
```

不需要前端，不需要登录，不需要数据库设计，也不需要 Agent。

只要一个 Python 脚本能完成整个流程，你后面的开发就会轻松很多。

---

## 我认为最终最合理的开发路线

|版本|产品目标|核心能力|建议技术|
|---|---|---|---|
|**V0**|技术验证（PoC）|跑通 RAG 全流程|Python + LangChain|
|**V1**|可用知识库|上传 Markdown、RAG 问答|FastAPI + PostgreSQL + pgvector|
|**V2**|知识管理|分类、标签、摘要、CRUD|PostgreSQL、LLM 信息抽取|
|**V3**|专业聊天|引用来源、聊天历史、多文档|RAG 优化|
|**V4**|单 Agent|Tool Calling、LangGraph|LangGraph|
|**V5**|长期记忆|用户偏好、学习目标|Memory|
|**V6**|学习助手|学习统计、复习建议、学习计划|Agent + 分析|
|**V7**|知识图谱|知识关联、关联推荐|Entity、Relation|
|**V8**|AI 第二大脑|Planner、多工具协作、自动学习辅助|多 Agent + Workflow|


| 文件夹/文件        | 作用                       | 是否负责业务逻辑 | 举例                                  |
| ------------- | ------------------------ | -------- | ----------------------------------- |
| **api/**      | 对外提供 HTTP 接口，接收用户请求并返回结果 | ❌ 不负责    | `/upload`、`/chat`、`/documents`      |
| **models/**   | 定义数据库中的数据结构（ORM 模型）      | ❌ 不负责    | `Document`、`Chunk`、`ChatHistory`    |
| **services/** | 实现业务逻辑，协调各模块完成一个功能       | ✅ **负责** | 上传文档、聊天问答、删除文档                      |
| **rag/**      | 实现 RAG 核心流程              | ✅ **负责** | Chunk、Embedding、Retriever、Generator |
| **parser/**   | 将各种格式文件解析为纯文本            | ✅（仅解析）   | Markdown、PDF、Word、TXT 解析            |
| **database/** | 管理数据库连接、Session、初始化数据库   | ❌ 不负责    | PostgreSQL 连接、SQLAlchemy Session    |
| **config/**   | 存放项目配置，统一读取环境变量          | ❌ 不负责    | API Key、数据库地址、模型名称                  |
| **main.py**   | FastAPI 项目启动入口，注册所有 API  | ❌ 不负责    | `FastAPI()`、`include_router()`      |
