## 1. 架构设计
```mermaid
graph TD
    subgraph "前端层 (Vue 3 + Vite)"
        UI["UI 组件 (Layout, ChatView, KnowledgeView)"]
        Store["状态管理 (Pinia)"]
        Router["路由 (Vue Router)"]
        Render["Markdown 引擎 (markdown-it + highlight.js)"]
        Network["网络层 (Fetch API + Axios)"]
    end
    
    subgraph "后端层 (Mock / 真实后端)"
        API_Chat["/chat (流式响应)"]
        API_Upload["/upload (文件上传)"]
        API_Docs["/docs (文档列表)"]
    end
    
    UI --> Store
    UI --> Router
    UI --> Render
    Store --> Network
    UI --> Network
    Network --> API_Chat
    Network --> API_Upload
    Network --> API_Docs
```

## 2. 技术栈说明
- **前端框架**: Vue 3 (Composition API) + TypeScript
- **构建工具**: Vite
- **路由**: vue-router
- **状态管理**: pinia
- **CSS 框架**: Tailwind CSS
- **排版插件**: @tailwindcss/typography
- **Markdown 渲染**: markdown-it, highlight.js
- **网络请求**: axios (用于普通请求), 原生 Fetch API (用于流式请求)
- **动画引擎**: @formkit/auto-animate

## 3. 路由定义
| 路由路径 | 视图组件 | 用途 |
|-------|---------|---------|
| `/` | - | 默认重定向到 `/chat` |
| `/chat` | `ChatView.vue` | 对话工作台页面 |
| `/knowledge` | `KnowledgeView.vue` | 知识库管理与文档上传页面 |

## 4. API 定义
由于目前仅开发前端，假设以下 API 接口契约：

```typescript
// POST /api/chat
// 请求体: { message: string }
// 响应: text/event-stream 或分块返回的字符串流

// POST /api/upload
// 请求体: FormData (file: File)
// 响应: { success: boolean, id: string, message: string }

// GET /api/docs
// 响应: { data: Array<{ id: string, name: string, status: 'parsing' | 'ready', createdAt: string }> }
```

## 5. 核心组件结构
- `src/App.vue`: 挂载 `RouterView`
- `src/components/Layout.vue`: 全局 App Shell 布局
- `src/views/ChatView.vue`: 对话视图
- `src/views/KnowledgeView.vue`: 知识库视图
- `src/components/MarkdownRenderer.vue`: 纯手工 Markdown 渲染器组件
- `src/api/chat.ts`: 封装 Fetch 流式请求
- `src/store/chatStore.ts`: Pinia store，管理对话状态
