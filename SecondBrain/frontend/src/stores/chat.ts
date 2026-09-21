import { defineStore } from 'pinia'
import { ref } from 'vue'
import { fetchChatStream, type ChatMessage } from '@/api/chat'

/**
 * 来源引用结构
 */
export interface Source {
  id: string
  content: string
  filename?: string
  node_type?: string
}

/**
 * 聊天消息结构
 */
export interface Message extends ChatMessage {
  id: string
  sources?: Source[] // 增加 sources 字段，用于展示参考来源
}

/**
 * 聊天状态管理
 */
export const useChatStore = defineStore('chat', () => {
  const messages = ref<Message[]>([])
  const isSending = ref(false)

  // 如果你有文档切换功能，可以在这里维护当前选中的文档ID
  const currentDocumentId = ref<string | undefined>(undefined)

  /**
   * 发送聊天消息
   */
  async function sendMessage(content: string) {
    if (!content.trim() || isSending.value) {
      return
    }

    // 1. 添加用户消息
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'user',
      content,
    })

    // 2. 创建AI消息占位
    const assistantMessage: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      sources: [], // 初始化为空数组
    }
    messages.value.push(assistantMessage)

    isSending.value = true

    try {
      // 3. 提取历史记录 (排除刚才创建的空AI消息和最新的用户提问)
      const history = messages.value.slice(0, -2).map((item) => ({
        role: item.role,
        content: item.content,
      }))

      // 4. 调用后端流式接口
      // ⚠️ 注意：你需要将 api/chat.ts 中的 fetchChatStream 入参改为接收如下对象
      const stream = fetchChatStream({
        query: content,
        document_id: currentDocumentId.value,
        history: history,
        top_k: 3,
      } as any) // 暂时用 any 绕过旧类型，建议同步修改 api 定义

      // 5. 缓冲区：用于处理 TCP 传输中可能被截断的数据包
      let buffer = ''

      for await (const chunk of stream) {
        /*
         * 【流式数据解析逻辑】
         * 因为我们需要同时接收文字和 sources，后端通常会按行返回 JSON 字符串，例如：
         * {"answer": "你"}
         * {"answer": "好"}
         * {"sources": [{"id":"1", "content":"..."}]}
         */
        buffer += chunk
        // 按照换行符拆分，确保每次解析的都是完整的 JSON 字符串
        const lines = buffer.split('\n')
        // 把最后可能不完整的一行（半截数据）留到下一次 chunk 到来时拼接
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.trim()) continue

          try {
            // 尝试解析后端传来的 JSON 块
            const data = JSON.parse(line)

            // 如果存在增量回答内容，累加到气泡中
            if (data.answer) {
              assistantMessage.content += data.answer
            }

            // 如果传来了参考来源（通常在最后一次请求中返回），赋值给 sources
            if (data.sources) {
              assistantMessage.sources = data.sources
            }
          } catch (e) {
            // 兼容处理：如果你的后端还没有改成 JSON 流，而是纯文本流，就直接拼接
            assistantMessage.content += line
          }
        }
      }

      // 处理结束后可能残留在 buffer 中的最后一点文本
      if (buffer.trim()) {
        try {
          const data = JSON.parse(buffer)
          if (data.answer) assistantMessage.content += data.answer
          if (data.sources) assistantMessage.sources = data.sources
        } catch (e) {
          assistantMessage.content += buffer
        }
      }
    } catch (error) {
      console.error('发送失败:', error)
      assistantMessage.content += '\n\n**[发送失败，请稍后重试]**'
    } finally {
      isSending.value = false
    }
  }

  function clearMessages() {
    messages.value = []
  }

  return {
    messages,
    isSending,
    currentDocumentId,
    sendMessage,
    clearMessages,
  }
})
