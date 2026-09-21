/**
 * 聊天 API
 */

import request from '@/utils/request'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

/**
 * 发送聊天流式请求 (对接后端的 RAG Chat 接口)
 */
export function fetchChatStream(data: {
  query: string
  document_id?: string
  history?: ChatMessage[]
  top_k?: number
}) {
  return request.stream('/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(data),
  })
}

/**
 * Markdown 文件上传
 */
export function uploadMarkdown(file: File) {
  const formData = new FormData()

  formData.append('file', file)

  return request.upload('/upload/md', formData)
}
