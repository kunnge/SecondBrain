import request from '@/utils/request'

export type MessageRole = 'user' | 'assistant' | 'tool'
export type MessageStatus = 'completed' | 'streaming' | 'stopped' | 'failed' | 'interrupted'

export interface ChatMessage {
  id: string
  conversation_id?: string
  sequence_no?: number
  role: MessageRole
  content: string
  sources?: ChatSource[]
  status?: MessageStatus
  error_message?: string | null
  created_at?: string | null
}

export interface ChatSource {
  id: string
  content: string
  filename?: string
  node_type?: string
  heading_path?: string
}

export interface ConversationSummary {
  id: string
  title: string
  created_at: string | null
  updated_at: string | null
  is_archived?: boolean
}

export interface StreamEvent {
  type: 'start' | 'delta' | 'sources' | 'done' | 'error'
  conversation?: ConversationSummary
  user_message?: ChatMessage
  assistant_message?: ChatMessage
  content?: string
  sources?: ChatSource[]
  message?: string
}

export function listConversations() {
  return request.get<ConversationSummary[]>('/conversations')
}

export function createConversation(title?: string) {
  return request.post<ConversationSummary>('/conversations', title ? { title } : {})
}

export function getConversationMessages(conversationId: string) {
  return request.get<ChatMessage[]>(`/conversations/${encodeURIComponent(conversationId)}/messages`)
}

export function renameConversation(conversationId: string, title: string) {
  return request.request<ConversationSummary>(
    `/conversations/${encodeURIComponent(conversationId)}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    },
  )
}

export function archiveConversation(conversationId: string, isArchived: boolean) {
  return request.request<ConversationSummary>(
    `/conversations/${encodeURIComponent(conversationId)}/archive`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_archived: isArchived }),
    },
  )
}

export function deleteConversation(conversationId: string) {
  return request.delete<{ deleted: boolean }>(
    `/conversations/${encodeURIComponent(conversationId)}`,
  )
}

export function fetchChatStream(
  conversationId: string,
  query: string,
  signal: AbortSignal,
  documentId?: string,
) {
  return request.stream('/conversations/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      conversation_id: conversationId,
      query,
      document_id: documentId,
      top_k: 4,
    }),
    signal,
  })
}

export function editQuestionStream(
  conversationId: string,
  messageId: string,
  content: string,
  signal: AbortSignal,
  documentId?: string,
) {
  return request.stream(
    `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/edit`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({ content, document_id: documentId, top_k: 4 }),
      signal,
    },
  )
}

export function regenerateAnswerStream(
  conversationId: string,
  messageId: string,
  signal: AbortSignal,
  documentId?: string,
) {
  return request.stream(
    `/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/regenerate`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({ document_id: documentId, top_k: 4 }),
      signal,
    },
  )
}

export function uploadMarkdown(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return request.upload('/upload/md', formData)
}
