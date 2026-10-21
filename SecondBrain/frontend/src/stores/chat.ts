import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  createConversation as createConversationRequest,
  deleteConversation as deleteConversationRequest,
  editQuestionStream,
  fetchChatStream,
  getConversationMessages,
  listConversations,
  regenerateAnswerStream,
  renameConversation as renameConversationRequest,
  type ChatMessage,
  type ConversationSummary,
  type StreamEvent,
} from '@/api/chat'

const ACTIVE_CONVERSATION_KEY = 'second-brain-active-conversation'

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])
  const conversations = ref<ConversationSummary[]>([])
  const activeConversationId = ref<string | null>(null)
  const activeConversation = computed(
    () => conversations.value.find((item) => item.id === activeConversationId.value) ?? null,
  )
  const isSending = ref(false)
  const isLoading = ref(false)
  const errorMessage = ref('')
  const currentDocumentId = ref<string | undefined>(undefined)
  let activeController: AbortController | null = null
  let activeStreamPromise: Promise<void> | null = null

  const createId = () => {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`
  }

  function rememberActiveConversation(id: string | null) {
    activeConversationId.value = id
    if (typeof localStorage !== 'undefined') {
      if (id) localStorage.setItem(ACTIVE_CONVERSATION_KEY, id)
      else localStorage.removeItem(ACTIVE_CONVERSATION_KEY)
    }
  }

  function applyConversation(conversation: ConversationSummary) {
    const index = conversations.value.findIndex((item) => item.id === conversation.id)
    if (index >= 0) conversations.value[index] = conversation
    else conversations.value.unshift(conversation)
    conversations.value.sort((a, b) => {
      const aTime = a.updated_at ? Date.parse(a.updated_at) : 0
      const bTime = b.updated_at ? Date.parse(b.updated_at) : 0
      return bTime - aTime
    })
  }

  async function refreshConversations() {
    conversations.value = await listConversations()
  }

  async function initialize() {
    isLoading.value = true
    errorMessage.value = ''
    try {
      await refreshConversations()
      const savedId = typeof localStorage !== 'undefined'
        ? localStorage.getItem(ACTIVE_CONVERSATION_KEY)
        : null
      const initial = conversations.value.find((item) => item.id === savedId)
        ?? conversations.value[0]
      rememberActiveConversation(initial?.id ?? null)
      if (initial) {
        messages.value = await getConversationMessages(initial.id)
      } else {
        messages.value = []
      }
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '无法加载会话'
    } finally {
      isLoading.value = false
    }
  }

  async function stopGeneration() {
    activeController?.abort()
    if (activeStreamPromise) {
      await activeStreamPromise.catch(() => undefined)
    }
  }

  async function startNewConversation() {
    await stopGeneration()
    const conversation = await createConversationRequest()
    applyConversation(conversation)
    rememberActiveConversation(conversation.id)
    messages.value = []
    errorMessage.value = ''
    return conversation
  }

  async function selectConversation(conversationId: string) {
    if (conversationId === activeConversationId.value) return
    await stopGeneration()
    rememberActiveConversation(conversationId)
    messages.value = []
    isLoading.value = true
    errorMessage.value = ''
    try {
      messages.value = await getConversationMessages(conversationId)
    } catch (error) {
      messages.value = []
      errorMessage.value = error instanceof Error ? error.message : '无法加载会话消息'
    } finally {
      isLoading.value = false
    }
  }

  async function renameConversation(conversationId: string, title: string) {
    const updated = await renameConversationRequest(conversationId, title.trim())
    applyConversation(updated)
  }

  async function removeConversation(conversationId: string) {
    if (conversationId === activeConversationId.value) await stopGeneration()
    await deleteConversationRequest(conversationId)
    conversations.value = conversations.value.filter((item) => item.id !== conversationId)
    if (conversationId === activeConversationId.value) {
      const next = conversations.value[0]
      rememberActiveConversation(next?.id ?? null)
      messages.value = next ? await getConversationMessages(next.id) : []
    }
  }

  function parseEventBlock(block: string): StreamEvent | null {
    const data = block
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
      .join('\n')
    if (!data) return null
    try {
      return JSON.parse(data) as StreamEvent
    } catch {
      return null
    }
  }

  function handleStreamEvent(
    event: StreamEvent,
    conversationId: string,
    userMessage: ChatMessage,
    assistantMessage: ChatMessage,
  ) {
    if (event.type === 'start') {
      if (event.user_message) Object.assign(userMessage, event.user_message)
      if (event.assistant_message) Object.assign(assistantMessage, event.assistant_message)
      if (event.conversation) applyConversation(event.conversation)
      return
    }
    if (event.type === 'delta' && event.content) {
      assistantMessage.content += event.content
      assistantMessage.status = 'streaming'
      return
    }
    if (event.type === 'sources') {
      assistantMessage.sources = event.sources ?? []
      return
    }
    if (event.type === 'done') {
      assistantMessage.status = 'completed'
      assistantMessage.sources = event.sources ?? []
      assistantMessage.error_message = null
      return
    }
    if (event.type === 'error') {
      assistantMessage.status = 'failed'
      assistantMessage.error_message = event.message ?? '回答生成失败，请重试。'
    }
    if (conversationId === activeConversationId.value && event.type === 'error') {
      errorMessage.value = ''
    }
  }

  async function consumeStream(
    conversationId: string,
    userMessage: ChatMessage,
    assistantMessage: ChatMessage,
    streamFactory: (signal: AbortSignal) => AsyncGenerator<string>,
  ) {
    if (isSending.value) return
    const controller = new AbortController()
    activeController = controller
    isSending.value = true
    let buffer = ''
    let terminalEventReceived = false
    const run = (async () => {
      try {
        const stream = streamFactory(controller.signal)
        for await (const chunk of stream) {
          buffer += chunk.replace(/\r\n/g, '\n')
          let boundary = buffer.indexOf('\n\n')
          while (boundary >= 0) {
            const event = parseEventBlock(buffer.slice(0, boundary))
            buffer = buffer.slice(boundary + 2)
            if (event) {
              handleStreamEvent(event, conversationId, userMessage, assistantMessage)
              if (event.type === 'done' || event.type === 'error') terminalEventReceived = true
            }
            boundary = buffer.indexOf('\n\n')
          }
        }
        if (buffer.trim()) {
          const event = parseEventBlock(buffer)
          if (event) {
            handleStreamEvent(event, conversationId, userMessage, assistantMessage)
            if (event.type === 'done' || event.type === 'error') terminalEventReceived = true
          }
        }
        if (!terminalEventReceived && !controller.signal.aborted) {
          assistantMessage.status = 'interrupted'
          assistantMessage.error_message = '连接中断，可以重新生成回答。'
        }
      } catch (error) {
        if (controller.signal.aborted) {
          assistantMessage.status = 'stopped'
          assistantMessage.error_message = null
        } else {
          assistantMessage.status = 'failed'
          assistantMessage.error_message = error instanceof Error
            ? error.message
            : '回答生成失败，请重试。'
        }
      } finally {
        if (controller.signal.aborted && !terminalEventReceived) {
          assistantMessage.status = 'stopped'
          assistantMessage.error_message = null
        }
        isSending.value = false
        if (activeController === controller) activeController = null
        activeStreamPromise = null
        try {
          await refreshConversations()
        } catch {
          // Keep the streamed answer visible even if refreshing the sidebar fails.
        }
      }
    })()
    activeStreamPromise = run
    await run
  }

  async function sendMessage(content: string) {
    const query = content.trim()
    if (!query || isSending.value) return
    let conversationId = activeConversationId.value
    if (!conversationId) {
      const conversation = await startNewConversation()
      conversationId = conversation.id
    }
    errorMessage.value = ''
    const userMessage: ChatMessage = {
      id: createId(), role: 'user', content: query, status: 'completed',
    }
    const assistantMessage: ChatMessage = {
      id: createId(), role: 'assistant', content: '', sources: [], status: 'streaming',
    }
    messages.value.push(userMessage, assistantMessage)
    await consumeStream(
      conversationId,
      userMessage,
      assistantMessage,
      (signal) => fetchChatStream(
        conversationId as string,
        query,
        signal,
        currentDocumentId.value,
      ),
    )
  }

  async function editMessage(messageId: string, content: string) {
    const query = content.trim()
    const conversationId = activeConversationId.value
    const index = messages.value.findIndex((item) => item.id === messageId)
    if (!query || !conversationId || index < 0 || isSending.value) return
    const userMessage = messages.value[index]
    if (userMessage.role !== 'user') return
    userMessage.content = query
    userMessage.status = 'completed'
    messages.value.splice(index + 1)
    const assistantMessage: ChatMessage = {
      id: createId(), role: 'assistant', content: '', sources: [], status: 'streaming',
    }
    messages.value.push(assistantMessage)
    await consumeStream(
      conversationId,
      userMessage,
      assistantMessage,
      (signal) => editQuestionStream(
        conversationId,
        messageId,
        query,
        signal,
        currentDocumentId.value,
      ),
    )
  }

  async function regenerateMessage(messageId: string) {
    const conversationId = activeConversationId.value
    const index = messages.value.findIndex((item) => item.id === messageId)
    if (!conversationId || index < 0 || isSending.value) return
    const assistantMessage = messages.value[index]
    if (assistantMessage.role !== 'assistant') return
    const userMessage = [...messages.value.slice(0, index)]
      .reverse()
      .find((item) => item.role === 'user')
    if (!userMessage) return
    messages.value.splice(index + 1)
    assistantMessage.content = ''
    assistantMessage.sources = []
    assistantMessage.status = 'streaming'
    assistantMessage.error_message = null
    await consumeStream(
      conversationId,
      userMessage,
      assistantMessage,
      (signal) => regenerateAnswerStream(
        conversationId,
        messageId,
        signal,
        currentDocumentId.value,
      ),
    )
  }

  return {
    messages,
    conversations,
    activeConversationId,
    activeConversation,
    isSending,
    isLoading,
    errorMessage,
    currentDocumentId,
    initialize,
    startNewConversation,
    selectConversation,
    renameConversation,
    removeConversation,
    sendMessage,
    editMessage,
    regenerateMessage,
    stopGeneration,
  }
})
